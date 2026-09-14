"""Where a running song sends its progress.

A worker next to the database writes to Postgres (DbReporter). A one-off GPU job on Modal or CoreWeave only gets
the web app's URL and a token for its one song, and reports over HTTP (HttpReporter), so the database is never
exposed to the internet. The token covers one attempt: a job left over from an earlier attempt is turned away.
"""

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from typing import Protocol

from yue2 import db


class Reporter(Protocol):
    def start(self) -> dict:
        """The song to run (id, source, url, takes), with progress from any earlier attempt cleared."""

    def event(self, data: dict) -> None: ...

    def heartbeat(self) -> None: ...

    def finish(self, result: dict) -> None: ...

    def fail(self, error: str) -> None: ...


def song_token(secret: str, song_id: str, attempt: int) -> str:
    return hmac.new(secret.encode(), f"{song_id}:{attempt}".encode(), hashlib.sha256).hexdigest()


def check_token(secret: str, song_id: str, attempt: int, token: str) -> bool:
    return bool(secret) and hmac.compare_digest(song_token(secret, song_id, attempt), token)


class DbReporter:
    def __init__(self, database_url: str, song_id: str):
        self.database_url = database_url
        self.song_id = str(song_id)
        self.conn = db.connect(database_url)

    def start(self) -> dict:
        db.restart(self.conn, self.song_id)
        return db.get(self.conn, self.song_id)

    def event(self, data: dict) -> None:
        db.add_event(self.conn, self.song_id, data)

    def heartbeat(self) -> None:  # called from a background thread, so it uses its own connection
        with db.connect(self.database_url) as conn:
            db.heartbeat(conn, self.song_id)

    def finish(self, result: dict) -> None:
        db.finish(self.conn, self.song_id, result)
        self.conn.close()

    def fail(self, error: str) -> None:
        db.fail(self.conn, self.song_id, error)
        self.conn.close()


class HttpReporter:
    def __init__(self, api_url: str, song_id: str, token: str, retries: int = 4):
        self.base = f"{api_url.rstrip('/')}/api/runner/songs/{song_id}"
        self.token = token
        self.retries = retries

    def _post(self, action: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            f"{self.base}/{action}", data=json.dumps(body or {}, default=str).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                     "User-Agent": "yue2-runner"})
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code < 500 or attempt == self.retries - 1:
                    raise RuntimeError(f"web app refused {action}: {error.code} {error.read()[:200]!r}") from error
            except OSError:
                if attempt == self.retries - 1:
                    raise
            time.sleep(2 ** attempt)
        raise AssertionError("unreachable")

    def start(self) -> dict:
        return self._post("start")

    def event(self, data: dict) -> None:
        self._post("events", data)

    def heartbeat(self) -> None:
        self._post("heartbeat")

    def finish(self, result: dict) -> None:
        self._post("finish", result)

    def fail(self, error: str) -> None:
        self._post("fail", {"error": error})

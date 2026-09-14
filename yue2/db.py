"""Postgres holds songs, their progress events, and the job queue (no separate queue service).

Workers claim the oldest queued song with FOR UPDATE SKIP LOCKED, so any number of workers on any machines can
share one database. A running song whose worker stops sending heartbeats is put back in the queue.
"""

import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
    id uuid PRIMARY KEY,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    source text NOT NULL,
    url text NOT NULL DEFAULT '',
    takes int NOT NULL,
    title text,
    error text,
    result jsonb,
    worker text,
    attempts int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    heartbeat_at timestamptz
);
CREATE INDEX IF NOT EXISTS songs_queued ON songs (created_at) WHERE status = 'queued';
CREATE TABLE IF NOT EXISTS song_events (
    song_id uuid NOT NULL REFERENCES songs (id) ON DELETE CASCADE,
    seq int NOT NULL,
    data jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (song_id, seq)
);
"""

MAX_ATTEMPTS = 2
STALE_AFTER = "15 minutes"


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA)


def create_song(conn, source: str, url: str, takes: int) -> str:
    song_id = str(uuid.uuid4())
    conn.execute("INSERT INTO songs (id, source, url, takes) VALUES (%s, %s, %s, %s)", (song_id, source, url, takes))
    return song_id


def claim(conn, worker: str) -> dict | None:
    """Take the oldest queued song, first returning abandoned ones to the queue."""
    conn.execute(f"""
        UPDATE songs SET status = CASE WHEN attempts >= {MAX_ATTEMPTS} THEN 'failed' ELSE 'queued' END,
               error = CASE WHEN attempts >= {MAX_ATTEMPTS} THEN 'worker stopped responding' ELSE error END
        WHERE status = 'running' AND heartbeat_at < now() - interval '{STALE_AFTER}'""")
    return conn.execute("""
        UPDATE songs SET status = 'running', worker = %s, attempts = attempts + 1,
               started_at = now(), heartbeat_at = now(), error = NULL
        WHERE id = (SELECT id FROM songs WHERE status = 'queued' ORDER BY created_at
                    FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING *""", (worker,)).fetchone()


def heartbeat(conn, song_id: str) -> None:
    conn.execute("UPDATE songs SET heartbeat_at = now() WHERE id = %s", (song_id,))


def add_event(conn, song_id: str, event: dict) -> None:
    conn.execute("""
        INSERT INTO song_events (song_id, seq, data)
        VALUES (%s, (SELECT coalesce(max(seq), 0) + 1 FROM song_events WHERE song_id = %s), %s)""",
                 (song_id, song_id, Jsonb(event)))
    if event.get("step") == "setup":
        conn.execute("UPDATE songs SET title = %s WHERE id = %s", (event.get("topic"), song_id))
    heartbeat(conn, song_id)


def restart(conn, song_id: str) -> None:
    """A retried song starts its progress over."""
    conn.execute("DELETE FROM song_events WHERE song_id = %s", (song_id,))


def finish(conn, song_id: str, result: dict) -> None:
    conn.execute("UPDATE songs SET status = 'done', result = %s, finished_at = now() WHERE id = %s", (Jsonb(result), song_id))


def fail(conn, song_id: str, error: str) -> None:
    conn.execute("UPDATE songs SET status = 'failed', error = %s, finished_at = now() WHERE id = %s", (error[:2000], song_id))


def get(conn, song_id: str) -> dict | None:
    song = conn.execute("SELECT * FROM songs WHERE id = %s", (song_id,)).fetchone()
    if song:
        song["events"] = [r["data"] for r in conn.execute(
            "SELECT data FROM song_events WHERE song_id = %s ORDER BY seq", (song_id,)).fetchall()]
    return song


def recent(conn, limit: int = 30) -> list[dict]:
    return conn.execute("""
        SELECT id, status, title, url, created_at, finished_at, error,
               (result -> 'best' ->> 'intelligibility')::float AS clarity,
               (result -> 'best' ->> 'faithfulness')::float AS faithfulness
        FROM songs ORDER BY created_at DESC LIMIT %s""", (limit,)).fetchall()


def queue_position(conn, song_id: str) -> int:
    row = conn.execute("""
        SELECT count(*) AS ahead FROM songs
        WHERE status = 'queued' AND created_at < (SELECT created_at FROM songs WHERE id = %s)""", (song_id,)).fetchone()
    return row["ahead"]


__all__ = ["connect", "init_schema", "create_song", "claim", "heartbeat", "add_event", "restart", "finish", "fail",
           "get", "recent", "queue_position"]

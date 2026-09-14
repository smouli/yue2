"""Dispatcher: runs queued songs as one-off jobs on a runner (Modal, CoreWeave or local processes) instead of on an
always-on worker. `python -m yue2 dispatch`

For each song it claims, it starts `python -m yue2 run-song ID` with only the settings that job needs plus a token
for that song, then watches the job. While the job runs, the dispatcher keeps the song's heartbeat alive (covering
image pulls and weight loading). A job that ends without finishing its song sends the song back to the queue, or
fails it after db.MAX_ATTEMPTS.
"""

import logging
import os
import time

from yue2 import db, report
from yue2.config import Settings
from yue2.runners import base as runners

log = logging.getLogger("yue2.dispatcher")

# Settings a job gets from the dispatcher's environment. Nothing else crosses over (no database URL).
FORWARDED = (
    "YUE2_MODELS", "YUE2_STORAGE", "S3_ENDPOINT", "S3_REGION", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY",
    "LLM_BASE_URL", "LLM_API_KEY", "LLM_PROJECT", "WRITER_MODEL", "ANALYST_MODEL",
    "WEAVE_PROJECT", "WANDB_API_KEY", "HF_TOKEN", "YUE2_MELODY", "YUE2_TAKES", "YUE2_BPM", "YUE2_FETCH_MODELS",
)


def job_env(settings: Settings, song_id: str | None = None, attempt: int = 0) -> dict[str, str]:
    env = {name: os.environ[name] for name in FORWARDED if os.environ.get(name)}
    env["YUE2_MODELS"] = settings.models
    env["YUE2_API_URL"] = settings.api_url
    if song_id:
        env["YUE2_SONG_TOKEN"] = report.song_token(settings.runner_secret, str(song_id), attempt)
    return env


def check(settings: Settings, runner: runners.Runner) -> None:
    if not settings.runner_secret:
        raise SystemExit("Set YUE2_RUNNER_SECRET (the same value on the web app) so jobs can report progress.")
    if runner.remote and settings.storage != "s3":
        raise SystemExit(f"{runner.name} jobs run elsewhere, so they need shared storage: set YUE2_STORAGE=s3.")
    if runner.remote and ("localhost" in settings.api_url or "127.0.0.1" in settings.api_url):
        raise SystemExit(f"{runner.name} jobs can't reach {settings.api_url}: set YUE2_API_URL to the web app's "
                         "public address.")


def watch(conn, runner: runners.Runner) -> int:
    """Check this runner's jobs; returns how many are still running."""
    running = 0
    for song in db.running_on(conn, runner.name):
        song_id, ref = str(song["id"]), song["runner_ref"]
        if not ref:  # claimed, job not started yet (another dispatcher is launching it)
            running += 1
            continue
        try:
            code = runner.poll(ref)
        except Exception:
            log.warning("couldn't check job %s for %s", ref, song_id, exc_info=True)
            running += 1
            continue
        if code is None:
            db.heartbeat(conn, song_id)
            running += 1
            continue
        state = db.retry_or_fail(conn, song_id, f"The {runner.name} job ended (exit code {code}) before the song "
                                                "was finished.")
        if state:  # None: the job reported done or failed before it exited, as it should
            log.warning("job %s for %s exited with %s; song is now %s", ref, song_id, code, state)
    return running


def launch_next(conn, settings: Settings, runner: runners.Runner) -> bool:
    song = db.claim(conn, runner.name)
    if not song:
        return False
    song_id = str(song["id"])
    try:
        ref = runner.launch(["run-song", song_id], job_env(settings, song_id, song["attempts"]))
    except Exception as error:
        log.exception("couldn't start a job for %s", song_id)
        db.retry_or_fail(conn, song_id, f"Couldn't start a {runner.name} job: {error}")
        return True
    db.set_runner_ref(conn, song_id, ref)
    log.info("started %s job %s for %s (attempt %s)", runner.name, ref, song_id, song["attempts"])
    return True


def main(poll_seconds: float = 5.0, once: bool = False, runner: runners.Runner | None = None) -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    runner = runner or runners.load(settings)
    check(settings, runner)
    log.info("dispatching to %s (up to %s at once, models=%s)", runner.name, settings.max_parallel, settings.models)
    with db.connect(settings.database_url) as conn:
        db.init_schema(conn)
        while True:
            running = watch(conn, runner)
            while running < settings.max_parallel and launch_next(conn, settings, runner):
                running += 1
            if once and running == 0:
                return
            time.sleep(poll_seconds)


def remote(args: list[str], poll_seconds: float = 10.0) -> int:
    """Run any yue2 command as a one-off job on the runner and wait, e.g. `remote fetch-models`."""
    settings = Settings.from_env()
    runner = runners.load(settings)
    ref = runner.launch(args, job_env(settings))
    print(f"started {runner.name} job {ref}: python -m yue2 {' '.join(args)} (logs are in the {runner.name} "
          "dashboard)", flush=True)
    try:
        while (code := runner.poll(ref)) is None:
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        runner.stop(ref)
        raise
    print(f"job {ref} exited with code {code}")
    return code

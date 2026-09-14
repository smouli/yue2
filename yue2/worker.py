"""Running songs on a GPU, two ways:

- `python -m yue2 worker`: an always-on worker (a GPU Droplet or VM) that claims queued songs from Postgres.
- `python -m yue2 run-song ID`: one song in a one-off job started by the dispatcher (Modal or CoreWeave sandbox),
  reporting to the web API instead of the database.
"""

import json
import logging
import socket
import threading
import time
import traceback

from yue2 import db, loop, melody, report, storage, tracing
from yue2.config import Settings
from yue2.models import base as models_base

log = logging.getLogger("yue2.worker")
PROFILE_KEY = "melodies/{name}/{file}"
HEARTBEAT_SECONDS = 30


def ensure_melody(settings: Settings, store, models) -> None:
    """Make sure the melody profile is on this machine: local folder, else storage, else (fake models) generate one."""
    if all((settings.melody_dir / f).exists() for f in melody.PROFILE_FILES):
        return
    keys = [PROFILE_KEY.format(name=settings.melody_name, file=f) for f in melody.PROFILE_FILES]
    if all(store.exists(k) for k in keys):
        for f, k in zip(melody.PROFILE_FILES, keys):
            store.get(k, settings.melody_dir / f)
        log.info("downloaded melody profile %s from storage", settings.melody_name)
        return
    if settings.models == "fake":
        from yue2.models.fake import write_profile
        write_profile(settings.melody_dir)
        log.info("generated a synthetic melody profile at %s", settings.melody_dir)
        return
    raise SystemExit(f"No melody profile for {settings.melody_name!r}. Run: python -m yue2 add-melody --audio SONG.mp3")


def prepare(settings: Settings):
    """Storage, models, melody profile and lyric writer: everything a song needs before it starts."""
    tracing.init(settings.weave_project)
    store = storage.load(settings)
    models = models_base.load(settings)
    ensure_melody(settings, store, models)
    if settings.fake_llm and settings.models == "local":
        raise SystemExit("Real models need a real lyric writer: set LLM_API_KEY (and LLM_BASE_URL, WRITER_MODEL).")
    llm = None
    if not settings.fake_llm:
        from yue2.llm import LLM
        llm = LLM(settings)
    return store, models, llm


def _beat(reporter: report.Reporter, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            reporter.heartbeat()
        except Exception:
            log.warning("heartbeat failed", exc_info=True)


def process(settings: Settings, reporter: report.Reporter, store, models, llm) -> None:
    song = reporter.start()
    song_id = str(song["id"])
    events = []

    def emit(event: dict) -> None:
        events.append(event)
        reporter.event(event)

    stop = threading.Event()
    threading.Thread(target=_beat, args=(reporter, stop), daemon=True).start()
    try:
        done = loop.run_song(song_id, song["source"], settings=settings, models=models, storage=store, llm=llm,
                             url=song["url"], takes=song["takes"], emit=emit)
        store.put_text(json.dumps(events, default=str), f"songs/{song_id}/events.json")
        reporter.finish(done)
        log.info("finished %s (clarity %.2f)", song_id, done["best"]["intelligibility"])
    except loop.ParagraphError as error:
        reporter.fail(str(error))
    except Exception:
        log.exception("song %s failed", song_id)
        reporter.fail(traceback.format_exc(limit=5))
    finally:
        stop.set()


def _logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def main(poll_seconds: float = 2.0, once: bool = False) -> None:
    settings = Settings.from_env()
    _logging()
    store, models, llm = prepare(settings)
    name = f"{socket.gethostname()}:{settings.models}"
    log.info("worker %s ready (models=%s, writer=%s, storage=%s)", name, settings.models,
             "fake" if llm is None else settings.writer_model, settings.storage)
    with db.connect(settings.database_url) as conn:
        db.init_schema(conn)
        while True:
            song = db.claim(conn, name)
            if song:
                log.info("claimed %s", song["id"])
                process(settings, report.DbReporter(settings.database_url, song["id"]), store, models, llm)
            elif once:
                return
            else:
                time.sleep(poll_seconds)


def run_one(song_id: str) -> None:
    """One song inside a one-off job. Exits non-zero only if the web app couldn't be told what happened."""
    settings = Settings.from_env()
    _logging()
    if not settings.song_token:
        raise SystemExit("run-song is started by the dispatcher, which sets YUE2_API_URL and YUE2_SONG_TOKEN.")
    reporter = report.HttpReporter(settings.api_url, song_id, settings.song_token)
    try:
        if settings.fetch_models and settings.models == "local":
            from yue2.models import weights
            weights.fetch(settings)
        store, models, llm = prepare(settings)
    except (Exception, SystemExit) as error:
        log.exception("job setup failed")
        reporter.fail(f"The GPU job couldn't start: {error}")
        raise SystemExit(1) from error
    process(settings, reporter, store, models, llm)

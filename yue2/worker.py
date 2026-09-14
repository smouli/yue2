"""GPU worker: claims queued songs from Postgres and runs the loop. Run as many as you have GPUs."""

import json
import logging
import socket
import threading
import time
import traceback
from pathlib import Path

from yue2 import db, loop, melody, storage, tracing
from yue2.config import Settings
from yue2.models import base as models_base

log = logging.getLogger("yue2.worker")
PROFILE_KEY = "melodies/{name}/{file}"


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


def _beat(conn_url: str, song_id: str, stop: threading.Event) -> None:
    with db.connect(conn_url) as conn:
        while not stop.wait(30):
            db.heartbeat(conn, song_id)


def process(settings: Settings, conn, store, models, llm, song: dict) -> None:
    song_id = str(song["id"])
    db.restart(conn, song_id)
    stop = threading.Event()
    threading.Thread(target=_beat, args=(settings.database_url, song_id, stop), daemon=True).start()
    try:
        done = loop.run_song(song_id, song["source"], settings=settings, models=models, storage=store, llm=llm,
                             url=song["url"], takes=song["takes"], emit=lambda e: db.add_event(conn, song_id, e))
        store.put_text(json.dumps(db.get(conn, song_id)["events"], default=str), f"songs/{song_id}/events.json")
        db.finish(conn, song_id, done)
        log.info("finished %s (clarity %.2f)", song_id, done["best"]["intelligibility"])
    except loop.ParagraphError as error:
        db.fail(conn, song_id, str(error))
    except Exception:
        log.exception("song %s failed", song_id)
        db.fail(conn, song_id, traceback.format_exc(limit=5))
    finally:
        stop.set()


def main(poll_seconds: float = 2.0, once: bool = False) -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    tracing.init(settings.weave_project)
    store = storage.load(settings)
    models = models_base.load(settings)
    ensure_melody(settings, store, models)
    llm = None
    if settings.fake_llm and settings.models == "local":
        raise SystemExit("Real models need a real lyric writer: set LLM_API_KEY (and LLM_BASE_URL, WRITER_MODEL).")
    if not settings.fake_llm:
        from yue2.llm import LLM
        llm = LLM(settings)
    name = f"{socket.gethostname()}:{settings.models}"
    log.info("worker %s ready (models=%s, writer=%s, storage=%s)", name, settings.models,
             "fake" if llm is None else settings.writer_model, settings.storage)
    with db.connect(settings.database_url) as conn:
        db.init_schema(conn)
        while True:
            song = db.claim(conn, name)
            if song:
                log.info("claimed %s", song["id"])
                process(settings, conn, store, models, llm, song)
            elif once:
                return
            else:
                time.sleep(poll_seconds)

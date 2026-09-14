"""python -m yue2 {api,worker,dispatch,run-song,remote,init-db,fetch-models,add-melody}"""

import argparse
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="yue2")
    sub = parser.add_subparsers(dest="command", required=True)
    api = sub.add_parser("api", help="serve the web app and API")
    api.add_argument("--host", default="0.0.0.0")
    api.add_argument("--port", type=int, default=8080)
    worker = sub.add_parser("worker", help="run songs from the queue")
    worker.add_argument("--once", action="store_true", help="exit when the queue is empty")
    dispatch = sub.add_parser("dispatch", help="run queued songs as one-off jobs on YUE2_RUNNER (modal, coreweave, process)")
    dispatch.add_argument("--once", action="store_true", help="exit when the queue is empty and no jobs are running")
    run_song = sub.add_parser("run-song", help="run one song inside a job (started by the dispatcher)")
    run_song.add_argument("song_id")
    remote = sub.add_parser("remote", help="run a yue2 command as a one-off job on YUE2_RUNNER, e.g. remote fetch-models")
    remote.add_argument("args", nargs=argparse.REMAINDER)
    sub.add_parser("init-db", help="create the database tables")
    sub.add_parser("fetch-models", help="download model weights into HF_HOME (GPU worker image)")
    melody = sub.add_parser("add-melody", help="transcribe a song into a melody profile and save it to storage")
    melody.add_argument("--audio", type=Path, help="source recording (not needed with fake models)")
    melody.add_argument("--audio-key", help="source recording already in storage (for add-melody in a remote job)")
    args = parser.parse_args(argv)

    from yue2.config import Settings

    settings = Settings.from_env()
    if args.command == "api":
        import uvicorn

        from yue2.api.app import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
    elif args.command == "worker":
        from yue2 import worker as worker_module

        worker_module.main(once=args.once)
    elif args.command == "dispatch":
        from yue2 import dispatcher

        dispatcher.main(once=args.once)
    elif args.command == "run-song":
        from yue2 import worker as worker_module

        worker_module.run_one(args.song_id)
    elif args.command == "remote":
        from yue2 import dispatcher

        if not args.args:
            sys.exit("usage: python -m yue2 remote <command> [args], e.g. remote fetch-models")
        sys.exit(dispatcher.remote(args.args))
    elif args.command == "init-db":
        from yue2 import db

        with db.connect(settings.database_url) as conn:
            db.init_schema(conn)
        print("database ready")
    elif args.command == "fetch-models":
        from yue2.models import weights

        weights.fetch(settings)
    elif args.command == "add-melody":
        from yue2 import melody as melody_module, storage
        from yue2.models import base
        from yue2.worker import PROFILE_KEY

        models = base.load(settings)
        store = storage.load(settings)
        if args.audio_key:
            args.audio = store.get(args.audio_key, Path(tempfile.mkdtemp()) / Path(args.audio_key).name)
        if settings.models != "fake" and not args.audio:
            sys.exit("--audio (or --audio-key) is required with local models")
        out = models.transcribe_song(args.audio, Path(tempfile.mkdtemp()) / settings.melody_name)
        profile = melody_module.load_profile(out)  # fails loudly if the transcription can't be used
        for name in melody_module.PROFILE_FILES:
            store.put(out / name, PROFILE_KEY.format(name=settings.melody_name, file=name))
        singable = [s for s in profile["sections"] if s.name in melody_module.SINGABLE]
        print(f"saved melody {settings.melody_name!r}: {len(singable)} singable sections, "
              f"capacity {melody_module.capacity(profile)} syllables")


if __name__ == "__main__":
    main()

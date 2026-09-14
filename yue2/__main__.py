"""python -m yue2 {api,worker,init-db,add-melody}"""

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
    sub.add_parser("init-db", help="create the database tables")
    sub.add_parser("fetch-models", help="download model weights into HF_HOME (GPU worker image)")
    melody = sub.add_parser("add-melody", help="transcribe a song into a melody profile and save it to storage")
    melody.add_argument("--audio", type=Path, help="source recording (not needed with fake models)")
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
    elif args.command == "init-db":
        from yue2 import db

        with db.connect(settings.database_url) as conn:
            db.init_schema(conn)
        print("database ready")
    elif args.command == "fetch-models":
        import os
        import subprocess

        # huggingface_hub's Python API rather than its CLI, whose name changed between releases.
        download = "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1])"
        for repo in ("m-a-p/YuE2-3B", "m-a-p/YuE2-Vae", "m-a-p/MERT-v2-FullSong", "openai/whisper-large-v3"):
            print("downloading", repo, flush=True)
            subprocess.run([settings.yue2_python, "-c", download, repo], check=True,
                           env={**os.environ, "HF_HOME": settings.hf_home})
        print("models ready in", settings.hf_home)
    elif args.command == "add-melody":
        from yue2 import melody as melody_module, storage
        from yue2.models import base
        from yue2.worker import PROFILE_KEY

        models = base.load(settings)
        if settings.models != "fake" and not args.audio:
            sys.exit("--audio is required with local models")
        out = models.transcribe_song(args.audio, Path(tempfile.mkdtemp()) / settings.melody_name)
        profile = melody_module.load_profile(out)  # fails loudly if the transcription can't be used
        store = storage.load(settings)
        for name in melody_module.PROFILE_FILES:
            store.put(out / name, PROFILE_KEY.format(name=settings.melody_name, file=name))
        singable = [s for s in profile["sections"] if s.name in melody_module.SINGABLE]
        print(f"saved melody {settings.melody_name!r}: {len(singable)} singable sections, "
              f"capacity {melody_module.capacity(profile)} syllables")


if __name__ == "__main__":
    main()

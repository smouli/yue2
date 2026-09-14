"""Model weights: downloaded into HF_HOME (a Docker volume, a Modal Volume or a CoreWeave volume) before first use."""

import os
import subprocess

from yue2.config import Settings

REPOS = ("m-a-p/YuE2-3B", "m-a-p/YuE2-Vae", "m-a-p/MERT-v2-FullSong", "openai/whisper-large-v3")

# huggingface_hub's Python API rather than its CLI, whose name changed between releases. Already-downloaded files
# are skipped, so this is quick on a warm volume.
_DOWNLOAD = "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1])"


def fetch(settings: Settings) -> None:
    for repo in REPOS:
        print("downloading", repo, flush=True)
        subprocess.run([settings.yue2_python, "-c", _DOWNLOAD, repo], check=True,
                       env={**os.environ, "HF_HOME": settings.hf_home})
    print("models ready in", settings.hf_home, flush=True)

"""All settings come from environment variables, so the same code runs on a laptop, a container sandbox or a
DigitalOcean GPU Droplet. See .env.example for the full list."""

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # Working files (renders in progress). Finished audio always goes to storage.
    home: Path
    database_url: str

    # Storage: "local" (a folder) or "s3" (DigitalOcean Spaces, AWS S3, MinIO...)
    storage: str
    storage_dir: Path
    s3_endpoint: str
    s3_region: str
    s3_bucket: str
    s3_access_key: str
    s3_secret_key: str

    # Models: "fake" (no GPU, for UI and pipeline testing) or "local" (YuE2, Whisper, SheetSage2 on this machine)
    models: str
    melody_name: str
    melody_dir: Path
    yue_skill_dir: Path
    yue2_python: str
    sheetsage_python: str
    sheetsage_model: str
    asr_python: str
    hf_home: str

    # LLM for the lyric writer and playbook coach: any OpenAI-compatible endpoint, or "fake"
    llm_base_url: str
    llm_api_key: str
    llm_project: str
    writer_model: str
    analyst_model: str

    # Tracing
    weave_project: str

    # Loop defaults
    takes: int
    bpm: int

    # One-off GPU jobs (python -m yue2 dispatch): "process" (local, for development), "modal" or "coreweave"
    runner: str
    api_url: str  # the web app's address as the jobs see it; they report progress there
    runner_secret: str  # signs per-song tokens; the web app and the dispatcher need the same value
    song_token: str  # set by the dispatcher inside a job
    max_parallel: int
    job_timeout: int
    fetch_models: bool  # download weights at job start (no persistent volume)
    worker_image: str  # the GPU worker image in a registry; Modal can build docker/worker-gpu.Dockerfile instead
    worker_python: str
    modal_app: str
    modal_gpu: str
    modal_volume: str
    cwsandbox_gpu_type: str
    cwsandbox_gpu_memory_gb: int
    cwsandbox_volume_id: str
    cwsandbox_auth: str

    @classmethod
    def from_env(cls) -> "Settings":
        home = Path(_env("YUE2_HOME", str(Path.home() / ".yue2"))).expanduser()
        melody_name = _env("YUE2_MELODY", "island-in-the-sun")
        return cls(
            home=home,
            database_url=_env("DATABASE_URL", "postgresql://yue2:yue2@localhost:5432/yue2"),
            storage=_env("YUE2_STORAGE", "local"),
            storage_dir=Path(_env("YUE2_STORAGE_DIR", str(home / "storage"))).expanduser(),
            s3_endpoint=_env("S3_ENDPOINT"),
            s3_region=_env("S3_REGION", "us-east-1"),
            s3_bucket=_env("S3_BUCKET"),
            s3_access_key=_env("S3_ACCESS_KEY"),
            s3_secret_key=_env("S3_SECRET_KEY"),
            models=_env("YUE2_MODELS", "fake"),
            melody_name=melody_name,
            melody_dir=Path(_env("YUE2_MELODY_DIR", str(home / "melodies" / melody_name))).expanduser(),
            yue_skill_dir=Path(_env("YUE2_SKILL_DIR", "/opt/YuE/skills/yue2-music")),
            yue2_python=_env("YUE2_PYTHON", "/opt/venvs/yue2/bin/python"),
            sheetsage_python=_env("SHEETSAGE_PYTHON", "/opt/venvs/sheetsage2/bin/python"),
            sheetsage_model=_env("SHEETSAGE_MODEL", "/models/SheetSage2"),
            asr_python=_env("ASR_PYTHON", "/opt/venvs/asr/bin/python"),
            hf_home=_env("HF_HOME", "/models/hf"),
            llm_base_url=_env("LLM_BASE_URL", "https://api.inference.wandb.ai/v1"),
            llm_api_key=_env("LLM_API_KEY"),
            llm_project=_env("LLM_PROJECT"),
            writer_model=_env("WRITER_MODEL", "google/gemma-4-31B-it"),
            analyst_model=_env("ANALYST_MODEL", "deepseek-ai/DeepSeek-V4-Pro"),
            weave_project=_env("WEAVE_PROJECT"),
            takes=int(_env("YUE2_TAKES", "3")),
            bpm=int(_env("YUE2_BPM", "90")),
            runner=_env("YUE2_RUNNER", "process"),
            api_url=_env("YUE2_API_URL", "http://localhost:8080").rstrip("/"),
            runner_secret=_env("YUE2_RUNNER_SECRET"),
            song_token=_env("YUE2_SONG_TOKEN"),
            max_parallel=int(_env("YUE2_MAX_PARALLEL", "2")),
            job_timeout=int(_env("YUE2_JOB_TIMEOUT", "3600")),
            fetch_models=_env("YUE2_FETCH_MODELS") in ("1", "true", "yes"),
            worker_image=_env("YUE2_WORKER_IMAGE"),
            worker_python=_env("YUE2_WORKER_PYTHON", "/opt/venvs/app/bin/python"),
            modal_app=_env("MODAL_APP", "yue2"),
            modal_gpu=_env("MODAL_GPU", "L40S"),
            modal_volume=_env("MODAL_VOLUME", "yue2-models"),
            cwsandbox_gpu_type=_env("CWSANDBOX_GPU_TYPE"),
            cwsandbox_gpu_memory_gb=int(_env("CWSANDBOX_GPU_MEMORY_GB", "40")),
            cwsandbox_volume_id=_env("CWSANDBOX_VOLUME_ID"),
            cwsandbox_auth=_env("CWSANDBOX_AUTH", "coreweave"),
        )

    @property
    def fake_llm(self) -> bool:
        """No LLM key (or WRITER_MODEL=fake) means the no-LLM writer; real models always need a real writer."""
        return self.writer_model == "fake" or not self.llm_api_key

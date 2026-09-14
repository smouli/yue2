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
        )

    @property
    def fake_llm(self) -> bool:
        """No LLM key (or WRITER_MODEL=fake) means the no-LLM writer; real models always need a real writer."""
        return self.writer_model == "fake" or not self.llm_api_key

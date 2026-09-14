"""What the loop needs from the audio models. Implementations: `local` (GPU) and `fake` (tests, GPU-free demos)."""

from pathlib import Path
from typing import Protocol


class Models(Protocol):
    def sing(self, lyrics: str, style: str, abc_path: Path, seed: int, out_dir: Path) -> dict:
        """Render one take. Returns {"audio": path, "request": path, "render_seconds": float}."""

    def listen(self, audio: Path, request_path: Path) -> dict:
        """Transcribe a take. Returns {"heard", "intelligibility", "lines": [{"line", "heard", "score", "start", "end"}]}."""

    def melody_check(self, audio: Path, source_pitches: list[int]) -> dict:
        """Re-transcribe a take and compare its vocal melody. Returns {"melody_fidelity", ...}."""

    def transcribe_song(self, audio: Path, out_dir: Path) -> Path:
        """Transcribe a source recording into a melody profile folder (score.abc, structure.lab, melody_vocal.lab)."""


def load(settings) -> Models:
    if settings.models == "fake":
        from yue2.models.fake import FakeModels
        return FakeModels()
    if settings.models == "local":
        from yue2.models.local import LocalModels
        return LocalModels(settings)
    raise ValueError(f"YUE2_MODELS must be 'fake' or 'local', not {settings.models!r}")

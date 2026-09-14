"""YuE2, Whisper and SheetSage2 on this machine's GPU.

Each model has its own Python environment (their PyTorch and Transformers pins conflict), so each step runs as a
subprocess. The worker image builds those environments; the paths come from Settings.
"""

import difflib
import json
import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class LocalModels:
    def __init__(self, settings):
        self.s = settings

    def _run(self, cmd: list[str], cwd: Path | None = None) -> float:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONSAFEPATH")}
        env["HF_HOME"] = self.s.hf_home
        env["PYTHONPATH"] = str(REPO_ROOT)  # lets the ASR scorer import yue2.text (pure Python)
        start = time.time()
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(f"{Path(cmd[1]).name} failed:\n{proc.stderr[-2000:]}")
        return round(time.time() - start, 1)

    def sing(self, lyrics: str, style: str, abc_path: Path, seed: int, out_dir: Path) -> dict:
        out_dir = Path(out_dir)
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        request_path = out_dir.with_suffix(".request.json")
        request_path.write_text(json.dumps({"id": out_dir.name, "style": style, "lyrics": lyrics, "cot": "melody",
                                            "seed": seed}, indent=2))
        seconds = self._run([self.s.yue2_python, "scripts/run_yue2.py", "generate", "--request", str(request_path),
                             "--cot", "melody", "--abc-file", str(abc_path), "--output", str(out_dir)],
                            cwd=self.s.yue_skill_dir)
        return {"audio": str(out_dir / "audio.flac"), "request": str(request_path), "render_seconds": seconds}

    def listen(self, audio: Path, request_path: Path) -> dict:
        out = Path(audio).with_name("asr.json")
        seconds = self._run([self.s.asr_python, "-m", "yue2.models.asr_score", str(audio), str(request_path),
                             "--output", str(out)], cwd=REPO_ROOT)
        return {**json.loads(out.read_text()), "asr_seconds": seconds}

    def _transcribe(self, audio: Path, out_dir: Path, task: str) -> float:
        return self._run([self.s.sheetsage_python, "scripts/transcribe.py", str(audio), "--task", task,
                          "--model", self.s.sheetsage_model, "--output", str(out_dir)], cwd=self.s.yue_skill_dir)

    def melody_check(self, audio: Path, source_pitches: list[int]) -> dict:
        out = Path(audio).parent / "melody-transcription"
        seconds = self._transcribe(audio, out, "melody-vocal")
        rows = [line.split("\t") for line in (out / "melody_vocal.lab").read_text().splitlines() if line.strip()]
        sung = [int(float(r[2])) for r in rows]
        intervals = lambda p: [b - a for a, b in zip(p, p[1:])]
        return {
            "melody_fidelity": round(difflib.SequenceMatcher(None, source_pitches, sung, autojunk=False).ratio(), 3),
            "interval_fidelity": round(difflib.SequenceMatcher(None, intervals(source_pitches), intervals(sung), autojunk=False).ratio(), 3),
            "source_notes": len(source_pitches), "sung_notes": len(sung), "transcribe_seconds": seconds,
        }

    def transcribe_song(self, audio: Path, out_dir: Path) -> Path:
        self._transcribe(audio, out_dir, "melody-vocal")
        return Path(out_dir)

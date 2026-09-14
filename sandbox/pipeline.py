"""Render + scoring steps for the loop. Stdlib only, so the notebook kernel can import it.

Each model runs in its own venv as a subprocess, with molab's kernel PYTHONPATH/PYTHONSAFEPATH removed.
"""

import difflib
import json
import os
import re
import subprocess
import time
from pathlib import Path

# Use local directory for outputs
HACK = Path.home() / ".yue2"
HACK.mkdir(parents=True, exist_ok=True)
SKILL = Path(__file__).parent  # Local sandbox directory
SOURCE_LAB = Path(__file__).parent / "runs/island-melody-vocal/melody_vocal.lab"


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONSAFEPATH")}
    env["HF_HOME"] = str(Path.home() / ".yue2/hf-cache")
    return env


def _run(cmd: list[str], cwd: Path = HACK) -> float:
    start = time.time()
    proc = subprocess.run(cmd, cwd=cwd, env=_env(), capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"{cmd[1]} failed:\n{proc.stderr[-2000:]}")
    return round(time.time() - start, 1)


def lyric_lines(lyrics: str) -> list[str]:
    return [line.strip() for line in lyrics.splitlines() if line.strip() and not line.strip().startswith("[")]


def count_syllables(word: str) -> int:
    """CMU dictionary count when `pronouncing` is installed, vowel-group heuristic otherwise."""
    word = re.sub(r"[^a-z']", "", word.lower()).strip("'")
    if not word:
        return 0
    try:
        import pronouncing
        phones = pronouncing.phones_for_word(word)
        if phones:
            return pronouncing.syllable_count(phones[0])
    except ImportError:
        pass
    word = word.replace("'", "")
    groups = re.findall(r"[aeiouy]+", word)
    n = len(groups)
    if word.endswith("e") and not word.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(n, 1)


def syllable_fit(lyrics: str, budget: list[int], tolerance: int = 0) -> dict:
    """Per-line syllables vs melody notes; 1.0 means every line is within `tolerance` of its phrase."""
    lines = lyric_lines(lyrics)
    per_line = []
    for line, notes in zip(lines, budget):
        from faithful import tokens  # spells out digits: "1971" is sung as four syllables
        syllables = sum(count_syllables(w) for w in tokens(line))
        off = max(0, abs(syllables - notes) - tolerance)
        per_line.append({"line": line, "syllables": syllables, "notes": notes,
                         "fit": round(max(0.0, 1 - off / notes), 3) if tolerance else
                                round(min(syllables, notes) / max(syllables, notes), 3)})
    score = sum(p["fit"] for p in per_line) / len(budget) if len(lines) == len(budget) else 0.0
    return {"syllable_fit": round(score, 3), "line_count_ok": len(lines) == len(budget), "syllable_lines": per_line}


def render(request: dict, out_dir: Path, abc_file: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    req_path = out_dir.with_suffix(".request.json")
    req_path.write_text(json.dumps(request, indent=2))
    seconds = _run([str(HACK / ".venv-yue2/bin/python"), "scripts/run_yue2.py", "generate",
                    "--request", str(req_path), "--cot", "melody", "--abc-file", str(abc_file),
                    "--output", str(out_dir)], cwd=SKILL)
    return {"audio": str(out_dir / "audio.flac"), "request": str(req_path), "render_seconds": seconds}


def _notes(lab: Path, start: float = 0, end: float = 1e9) -> list[int]:
    rows = [line.split("\t") for line in Path(lab).read_text().splitlines() if line.strip()]
    return [int(float(r[2])) for r in rows if start <= float(r[0]) < end]


def melody_fidelity(audio: str, ranges: list[tuple[float, float]]) -> dict:
    """Re-transcribe the render and compare its vocal melody to the source sections it was sung over."""
    out = Path(audio).parent.with_name(Path(audio).parent.name + "-transcription")
    seconds = _run([str(HACK / ".venv-sheetsage2/bin/python"), "scripts/transcribe.py", audio,
                    "--task", "melody-vocal", "--model", str(HACK / "models/SheetSage2"),
                    "--output", str(out)], cwd=SKILL)
    source = [p for start, end in ranges for p in _notes(SOURCE_LAB, start, end)]
    cover = _notes(out / "melody_vocal.lab")
    intervals = lambda p: [b - a for a, b in zip(p, p[1:])]
    return {
        "melody_fidelity": round(difflib.SequenceMatcher(None, source, cover, autojunk=False).ratio(), 3),
        "interval_fidelity": round(difflib.SequenceMatcher(None, intervals(source), intervals(cover), autojunk=False).ratio(), 3),
        "source_notes": len(source), "render_notes": len(cover), "transcribe_seconds": seconds,
    }


def intelligibility(audio: str, request_path: str) -> dict:
    out = Path(audio).with_name("asr.json")
    seconds = _run([str(HACK / ".venv-asr/bin/python"), str(Path(__file__).with_name("asr_score.py")), audio, request_path,
                    "--output", str(out)])
    result = json.loads(out.read_text())
    result["asr_seconds"] = seconds
    return result

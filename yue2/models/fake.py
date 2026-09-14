"""Stand-in models for tests and GPU-free demos.

The singer writes a short tone per lyric line (a real, playable WAV); the listener "hears" each line back with
deterministic errors that are more likely on long or crowded lines and change with the seed, so the loop's
rewriting, take selection and line locking behave as they would with real models.
"""

import hashlib
import json
import math
import struct
import wave
from pathlib import Path

from yue2.models.asr_score import letter_similarity
from yue2.text.syllables import count_text_syllables, lyric_lines

SECONDS_PER_LINE = 2.5
SAMPLE_RATE = 16000

# Phrase shape of the demo melody: note counts per line (counts only, no melody content).
FAKE_SECTIONS = [
    ("intro", []), ("verse", [7, 7, 7, 7]), ("chorus", [7, 8, 13]), ("verse", [7, 7, 7, 7, 7, 7, 13]),
    ("chorus", [7, 7, 13]), ("verse", [7, 8, 13]), ("chorus", [7, 7, 13]), ("outro", []),
]


def _unit(*parts) -> float:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


class FakeModels:
    def sing(self, lyrics: str, style: str, abc_path: Path, seed: int, out_dir: Path) -> dict:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        request_path = out_dir.with_suffix(".request.json")
        request_path.write_text(json.dumps({"style": style, "lyrics": lyrics, "seed": seed}, indent=2))
        lines = lyric_lines(lyrics)
        audio = out_dir / "audio.wav"
        with wave.open(str(audio), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            frames = bytearray()
            for i, _line in enumerate(lines):
                freq = 196 * 2 ** ((i % 8) / 12)
                for n in range(int(SECONDS_PER_LINE * SAMPLE_RATE)):
                    envelope = min(1.0, n / 800, (SECONDS_PER_LINE * SAMPLE_RATE - n) / 800)
                    frames += struct.pack("<h", int(6000 * envelope * math.sin(2 * math.pi * freq * n / SAMPLE_RATE)))
            w.writeframes(bytes(frames))
        return {"audio": str(audio), "request": str(request_path), "render_seconds": 0.1}

    def listen(self, audio: Path, request_path: Path) -> dict:
        request = json.loads(Path(request_path).read_text())
        results, heard_all = [], []
        for i, line in enumerate(lyric_lines(request["lyrics"])):
            words = line.split()
            crowding = count_text_syllables(line) / max(len(words), 1)
            p_miss = min(0.45, 0.04 + 0.05 * max(0.0, crowding - 1.6) + 0.02 * max(0, len(words) - 5))
            heard_words = [w if _unit(request["seed"], i, j, w) > p_miss else w[::-1] for j, w in enumerate(words)]
            heard = " ".join(heard_words)
            heard_all.append(heard)
            start = i * SECONDS_PER_LINE
            results.append({"line": line, "heard": heard, "wer": None, "score": round(letter_similarity(line, heard), 3),
                            "start": round(start, 2), "end": round(start + SECONDS_PER_LINE, 2)})
        weights = [max(len(r["line"]), 1) for r in results]
        clarity = sum(r["score"] * w for r, w in zip(results, weights)) / max(sum(weights), 1)
        return {"model": "fake", "heard": " ".join(heard_all), "intelligibility": round(clarity, 3), "lines": results}

    def melody_check(self, audio: Path, source_pitches: list[int]) -> dict:
        return {"melody_fidelity": 0.97, "interval_fidelity": 0.97, "source_notes": len(source_pitches),
                "sung_notes": len(source_pitches), "transcribe_seconds": 0.0}

    def transcribe_song(self, audio: Path, out_dir: Path) -> Path:
        return write_profile(out_dir)


def write_profile(out_dir: Path, bpm: int = 115) -> Path:
    """A synthetic melody profile with the demo song's phrase shape, in SheetSage2's file layout."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    note_len, gap, t = 0.3, 0.6, 0.0
    abc = ["X:1", "T:", "M:4/4", "L:1/16", f"Q:1/4={bpm}", 'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"', "K:G"]
    structure, notes = [], []
    for name, phrases in FAKE_SECTIONS:
        start = t
        for count in phrases:
            for k in range(count):
                notes.append((t, t + note_len, 60 + (k % 5)))
                t += note_len
            t += gap
        t += 1.0 if not phrases else 0.0
        structure.append((start, t, name))
        abc += [f"% {name}", "V: Vocal", "G4 A4 B4 c4 |" * max(1, sum(phrases) // 4)]
    (out_dir / "score.abc").write_text("\n".join(abc) + "\n")
    (out_dir / "structure.lab").write_text("".join(f"{a:.2f}\t{b:.2f}\t{n}\n" for a, b, n in structure))
    (out_dir / "melody_vocal.lab").write_text("".join(f"{a:.2f}\t{b:.2f}\t{p}\n" for a, b, p in notes))
    return out_dir

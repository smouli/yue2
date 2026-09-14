"""Melody profile: split a transcribed song into sections and phrases so any length of text can be sung.

SheetSage2 gives us a score (ABC, one block per section) and timed vocal notes. A phrase is a run of
notes without a pause; each phrase becomes one lyric line whose syllable budget is its note count.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_FILES = ("score.abc", "structure.lab", "melody_vocal.lab")
PHRASE_GAP_SECONDS = 0.35
SINGABLE = ("verse", "chorus")


@dataclass
class Section:
    name: str
    start: float
    end: float
    phrases: list[int]
    abc_lines: list[str] = field(repr=False)

    @property
    def notes(self) -> int:
        return sum(self.phrases)


def _timed_notes(lab: Path) -> list[tuple[float, float]]:
    rows = [line.split("\t") for line in lab.read_text().splitlines() if line.strip()]
    return [(float(r[0]), float(r[1])) for r in rows]


def _phrases(notes: list[tuple[float, float]], start: float, end: float) -> list[int]:
    inside = [n for n in notes if start <= n[0] < end]
    phrases, current, last_end = [], 0, None
    for onset, offset in inside:
        if last_end is not None and onset - last_end > PHRASE_GAP_SECONDS:
            phrases.append(current)
            current = 0
        current += 1
        last_end = offset
    if current:
        phrases.append(current)
    merged = []
    for count in phrases:  # a 1-2 note fragment is a pickup or tail, not a line of its own
        if count <= 2 and merged:
            merged[-1] += count
        else:
            merged.append(count)
    return merged


def load_profile(transcription: Path) -> dict:
    """Read a SheetSage2 transcription folder (score.abc, structure.lab, melody_vocal.lab)."""
    transcription = Path(transcription)
    abc = (transcription / "score.abc").read_text().splitlines()
    markers = [i for i, line in enumerate(abc) if line.startswith("% ")]
    header = abc[:markers[0]]

    # structure.lab splits some sections the ABC keeps whole (two verses in a row); merge equal neighbours.
    spans = []
    for line in (transcription / "structure.lab").read_text().splitlines():
        if not line.strip():
            continue
        start, end, label = line.split("\t")
        if spans and spans[-1][2] == label:
            spans[-1][1] = float(end)
        else:
            spans.append([float(start), float(end), label])

    notes = _timed_notes(transcription / "melody_vocal.lab")
    sections = []
    for k, i in enumerate(markers):
        name = abc[i][2:].strip()
        block = abc[i:markers[k + 1] if k + 1 < len(markers) else len(abc)]
        start, end, label = spans[k]
        assert label == name, f"section {k}: ABC says {name}, structure says {label}"
        sections.append(Section(name, start, end, _phrases(notes, start, end), block))
    return {"header": header, "sections": sections, "notes": [n for n in _pitched_notes(transcription / "melody_vocal.lab")],
            "transcription": str(transcription)}


def _pitched_notes(lab: Path) -> list[tuple[float, int]]:
    rows = [line.split("\t") for line in lab.read_text().splitlines() if line.strip()]
    return [(float(r[0]), int(float(r[2]))) for r in rows]


def section_pitches(profile: dict, sections: list["Section"]) -> list[int]:
    """The original melody's pitches under the chosen sections, for the melody check."""
    return [pitch for s in sections for onset, pitch in profile["notes"] if s.start <= onset < s.end]


MAX_REPEATS = 2  # the verse/chorus run can play twice (~3.5 minutes) for longer paragraphs


def plan_song(profile: dict, syllables: int) -> list[Section]:
    """The shortest run of verses and choruses, in song order (repeating if needed), with room for `syllables`."""
    singable = [s for s in profile["sections"] if s.name in SINGABLE]
    chosen = []
    for section in singable * MAX_REPEATS:
        chosen.append(section)
        if sum(s.notes for s in chosen) >= syllables:
            break
    return chosen


def capacity(profile: dict) -> int:
    return MAX_REPEATS * sum(s.notes for s in profile["sections"] if s.name in SINGABLE)


def tempo(profile: dict) -> int:
    return int(next(re.search(r"=(\d+)", l).group(1) for l in profile["header"] if l.startswith("Q:")))


def write_abc(profile: dict, sections: list[Section], path: Path, bpm: int | None = None) -> Path:
    """Write the chosen sections as one score; `bpm` slows or speeds the melody (dense text needs it slower)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [re.sub(r"^Q:1/4=\d+", f"Q:1/4={bpm}", l) if bpm else l for l in profile["header"]]
    for section in sections:
        lines += section.abc_lines
    path.write_text("\n".join(lines).rstrip() + "\n")
    return path


def budget(sections: list[Section]) -> list[int]:
    return [count for s in sections for count in s.phrases]


def lyrics_text(sections: list[Section], lines: list[str]) -> str:
    out, i = [], 0
    for section in sections:
        out.append(f"[{section.name.capitalize()}]")
        out += lines[i:i + len(section.phrases)]
        out.append("")
        i += len(section.phrases)
    return "\n".join(out).strip()

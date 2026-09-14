"""Syllable counting and syllable fit: how well each lyric line matches the notes of its melody phrase."""

import re

from yue2.text.faithful import tokens


def lyric_lines(lyrics: str) -> list[str]:
    """Sung lines, without section tags like [Verse]."""
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
    n = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(n, 1)


def count_text_syllables(text: str) -> int:
    return sum(count_syllables(w) for w in tokens(text))


def syllable_fit(lyrics: str, budget: list[int], tolerance: int = 0) -> dict:
    """Per-line syllables vs melody notes; 1.0 means every line is within `tolerance` of its phrase."""
    lines = lyric_lines(lyrics)
    per_line = []
    for line, notes in zip(lines, budget):
        syllables = count_text_syllables(line)  # numbers are spelled out: "1971" is sung as four syllables
        off = max(0, abs(syllables - notes) - tolerance)
        fit = max(0.0, 1 - off / notes) if tolerance else min(syllables, notes) / max(syllables, notes)
        per_line.append({"line": line, "syllables": syllables, "notes": notes, "fit": round(fit, 3)})
    count_ok = len(lines) == len(budget)
    score = sum(p["fit"] for p in per_line) / len(budget) if count_ok else 0.0
    return {"syllable_fit": round(score, 3), "line_count_ok": count_ok, "syllable_lines": per_line}

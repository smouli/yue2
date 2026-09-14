"""The lyric writer: set the source paragraph's own words to the melody's lines with minimal edits."""

from yue2 import tracing
from yue2.text.syllables import count_syllables, lyric_lines
from yue2.text.faithful import tokens

SYLLABLE_TOLERANCE = 1

SYSTEM = "You set existing text to music with minimal, faithful edits."


def _lyrics(sections: list[dict], lines: list[str]) -> str:
    out, k = [], 0
    for s in sections:
        out.append(f"[{s['name'].capitalize()}]")
        out += lines[k:k + len(s["phrases"])]
        out.append("")
        k += len(s["phrases"])
    return "\n".join(out).strip()


def prompt(source: str, sections: list[dict], feedback: str | None, previous: str | None,
           playbook: list[str] | None, locked: dict[int, str] | None) -> str:
    budget = [n for s in sections for n in s["phrases"]]
    layout, line_no = [], 0
    for s in sections:
        layout.append(f"[{s['name'].capitalize()}]")
        for n in s["phrases"]:
            line_no += 1
            layout.append(f"line {line_no}: {n} syllables (±{SYLLABLE_TOLERANCE})")
    user = f"""Source text to sing:
---
{source}
---
Set this text to an existing melody. Sing the source's own words, in the source's order, from start to end.
Make only the smallest edits needed to fit the syllable budget and be sung clearly, preferring in this order:
1. split sentences across lines at natural pauses
2. drop filler words (articles, some prepositions, "that", "which") and parenthetical asides
3. contractions, and numbers or symbols written out as spoken words
4. only if unavoidable: a shorter word with the same meaning
Never paraphrase, summarize, or add words the source does not contain. Keep technical terms exactly.
The melody has {len(budget)} lines:
""" + "\n".join(layout) + "\n"
    if playbook:
        user += "\nLessons from earlier songs:\n" + "\n".join(f"- {tip}" for tip in playbook)
    if previous:
        user += f"\nPrevious attempt:\n{previous}\n\nWhat went wrong and must be fixed:\n{feedback}\n" \
                "Keep lines that had no problems unchanged."
    if locked:
        user += "\nThese lines were sung clearly and are locked; return them exactly as written:\n" + \
                "\n".join(f"line {i + 1}: {text}" for i, text in sorted(locked.items()))
    return user + f'\nReturn JSON: {{"lines": [{len(budget)} strings]}}'


@tracing.op
def write(llm, model: str, source: str, sections: list[dict], feedback: str | None = None,
          previous: str | None = None, playbook: list[str] | None = None, locked: dict[int, str] | None = None,
          temperature: float = 0.7) -> str:
    budget = [n for s in sections for n in s["phrases"]]
    user = prompt(source, sections, feedback, previous, playbook, locked)
    lines = [str(line).strip() for line in llm.json(model, SYSTEM, user, max_tokens=4000, temperature=temperature)["lines"]]
    lines = lines[:len(budget)] + [""] * (len(budget) - len(lines))
    for i, text in (locked or {}).items():  # enforce locks even if the writer ignored them
        if i < len(lines):
            lines[i] = text
    return _lyrics(sections, lines)


def fake_write(source: str, sections: list[dict], locked: dict[int, str] | None = None, **_) -> str:
    """No-LLM writer for tests and GPU-free demos: spreads the source's words across the lines by syllable budget."""
    words = source.split()
    budget = [n for s in sections for n in s["phrases"]]
    costs = [max(1, sum(count_syllables(t) for t in tokens(w))) for w in words]
    scale = sum(costs) / max(sum(budget), 1)
    lines, i = [], 0
    for k, notes in enumerate(budget):
        lines_left = len(budget) - k
        line, syllables = [], 0
        while i < len(words) and len(words) - i > lines_left - 1:
            if line and syllables + costs[i] > notes * scale + SYLLABLE_TOLERANCE:
                break
            line.append(words[i])
            syllables += costs[i]
            i += 1
        lines.append(" ".join(line))
    if i < len(words):
        lines[-1] = (lines[-1] + " " + " ".join(words[i:])).strip()
    for k, text in (locked or {}).items():
        if k < len(lines):
            lines[k] = text
    return _lyrics(sections, lines)


def text_feedback(result: dict) -> str:
    notes = [f"line {i + 1} \"{l['line']}\" has {l['syllables']} syllables, needs {l['notes']} (±{SYLLABLE_TOLERANCE})"
             for i, l in enumerate(result["syllable_lines"]) if abs(l["syllables"] - l["notes"]) > SYLLABLE_TOLERANCE]
    if not result["line_count_ok"]:
        notes.append("write exactly one line per melody line")
    if result["dropped_words"]:
        notes.append("source words you dropped (put back what fits): " + ", ".join(result["dropped_words"][:20]))
    if result["added_words"]:
        notes.append("words not in the source (remove or replace with source wording): "
                     + ", ".join(f"line {a['line']} '{a['word']}'" for a in result["added_words"][:12]))
    return "\n".join(notes)


def listen_feedback(lines: list[dict], threshold: float) -> str:
    """Misheard lines, with fixes that keep the source's words (the writer must not reword)."""
    misheard = [f"line \"{l['line']}\" was heard as \"{l['heard'] or '(nothing)'}\"" for l in lines if l["score"] < threshold]
    if not misheard:
        return ""
    return "\n".join(misheard) + (
        "\nMake these lines clearer without changing the source's words: give long or technical words more room "
        "by moving a word to a neighbouring line, drop filler words, put a hard term at the start of its line, "
        "write acronyms and symbols as they are spoken (A T P, C O two), and avoid packing several hard terms into one line.")


__all__ = ["SYLLABLE_TOLERANCE", "write", "fake_write", "text_feedback", "listen_feedback", "lyric_lines"]

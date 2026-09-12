"""The playbook: general songwriting rules the loop learns from its own runs.

After each song, the coach reads what went wrong and which fixes worked, then updates a short list of
rules. The writer sees those rules on every future song. Each version is saved to disk and published
to Weave so the playbook's history is tracked alongside the runs that produced it.
"""

import json
from pathlib import Path

import weave

import loop
import pipeline

PLAYBOOK_PATH = pipeline.HACK / "playbook.json"
MAX_RULES = 10


def load() -> dict:
    if PLAYBOOK_PATH.exists():
        return json.loads(PLAYBOOK_PATH.read_text())
    return {"version": 0, "rules": [], "learned_from": []}


def save(playbook: dict) -> None:
    PLAYBOOK_PATH.write_text(json.dumps(playbook, indent=2))
    weave.publish(playbook, name="yue2-playbook")


def rules(playbook: dict) -> list[str]:
    return [r["rule"] for r in playbook["rules"]]


def evidence(history: list[dict]) -> dict:
    """Condense a run into what the coach needs: scores per pass and every line that was changed."""
    texts = [e for e in history if e["step"] == "text"]
    renders = [e for e in history if e["step"] == "render"]
    facts = next(e for e in history if e["step"] == "facts")
    done = next((e for e in history if e["step"] == "done"), None)

    text_fixes = []
    for a, b in zip(texts, texts[1:]):
        for i, (before, after) in enumerate(zip(pipeline.lyric_lines(a["lyrics"]), pipeline.lyric_lines(b["lyrics"]))):
            if before != after:
                syl_a = a["syllable_lines"][i] if i < len(a["syllable_lines"]) else {}
                syl_b = b["syllable_lines"][i] if i < len(b["syllable_lines"]) else {}
                text_fixes.append({
                    "before": before, "after": after, "notes": syl_a.get("notes"),
                    "syllables_before": syl_a.get("syllables"), "syllables_after": syl_b.get("syllables"),
                    "awkward_before": next((w["why"] for w in a.get("awkward_lines", []) if w["line"] == i + 1), None),
                    "awkward_after": next((w["why"] for w in b.get("awkward_lines", []) if w["line"] == i + 1), None),
                })

    listen_fixes = []
    for a, b in zip(renders, renders[1:]):
        for la, lb in zip(a["lines"], b["lines"]):
            if la["line"] != lb["line"]:
                listen_fixes.append({"before": la["line"], "heard_as": la["heard"], "clarity_before": la["score"],
                                     "after": lb["line"], "clarity_after": lb["score"]})

    misheard_final = [{"line": l["line"], "heard_as": l["heard"], "clarity": l["score"]}
                      for l in (renders[-1]["lines"] if renders else []) if l["score"] < 0.85]
    return {
        "topic": facts["topic"],
        "drafts": [{"pass": f"{e['render_pass']}.{e['text_pass']}", "syllable_fit": e["syllable_fit"],
                    "facts": e["fact_coverage"], "natural": e["natural"]} for e in texts],
        "renders": [{"pass": e["render_pass"], "clarity": e["intelligibility"]} for e in renders],
        "text_fixes": text_fixes[:20],
        "listen_fixes": listen_fixes,
        "still_misheard_at_end": misheard_final,
        "final": done["best"] if done else None,
    }


@weave.op
def coach(playbook: dict, run_evidence: dict) -> dict:
    """Update the playbook from one run's evidence. Returns the new playbook (version + 1)."""
    final = run_evidence["final"] or {}
    compact = {**run_evidence, "final": {k: final.get(k) for k in ("intelligibility", "fact_coverage", "syllable_fit", "natural", "lyrics")}}
    update = loop._chat_json(loop.ANALYST,
        "You maintain a playbook of general rules for an AI that writes educational song lyrics to a fixed melody "
        "(one syllable per note, strict per-line syllable budgets). A music model sings the lyrics and a speech "
        "recognizer checks whether each line is heard correctly. Rules must be general across topics, actionable, "
        "and under 25 words. Only add a rule when the evidence shows a failure it would prevent or a fix that worked.",
        f"""Current playbook:
{json.dumps(playbook['rules'], indent=1)}

Evidence from the latest song:
{json.dumps(compact, indent=1)}

Return the full updated playbook, at most {MAX_RULES} rules, most useful first. Keep rules still supported,
merge duplicates, drop rules the evidence contradicts.
Return JSON: {{"rules": [{{"rule": str, "evidence": short str}}], "changes": one sentence}}""",
        max_tokens=3000, temperature=0.2)
    return {
        "version": playbook["version"] + 1,
        "rules": update["rules"][:MAX_RULES],
        "changes": update.get("changes", ""),
        "learned_from": playbook["learned_from"] + [run_evidence["topic"]],
    }

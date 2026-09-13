"""The playbook: general songwriting rules the loop learns from its own runs.

After each song, the coach reads what went wrong and which fixes worked, then proposes rules. A rule only
joins the playbook if it wins an A/B test: first drafts for a fixed set of validation pages, written with
and without the rule, scored on syllable fit, facts taught and naturalness. The writer sees accepted rules
on every future song. Each version is saved to disk and published to Weave, including rejected proposals.
"""

import json
import statistics
from pathlib import Path

import weave
from weave.trace.util import ContextAwareThreadPoolExecutor

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


# ---------------------------------------------------------------------------------------------------------
# Gated learning: rules must earn their place.
# ---------------------------------------------------------------------------------------------------------

GATE_DATASET_PATH = pipeline.HACK / "runs/gate-dataset.json"
GATE_URLS = [f"https://en.wikipedia.org/wiki/{page}" for page in (
    "Moon", "Ancient_Egypt", "Electric_battery", "Rainforest", "Heart", "World_War_I", "Periodic_table", "Honey_bee")]
GATE_TRIALS = 5  # identical runs differ by ~0.02 at 3 trials; 5 trials and a 0.03 bar keep noise out
MIN_GAIN = 0.03        # a new rule must raise the mean first-draft score by this much
MAX_FIT_DROP = 0.03    # ...without costing more than this much syllable fit
MAX_CANDIDATES = 3


def gate_dataset() -> list[dict]:
    if GATE_DATASET_PATH.exists():
        return json.loads(GATE_DATASET_PATH.read_text())
    rows = []
    for url in GATE_URLS:
        facts = loop.extract_facts(loop.fetch_source(url))
        rows.append({"url": url, "topic": facts["topic"], "facts": facts["facts"], "quiz": facts["quiz"]})
    GATE_DATASET_PATH.write_text(json.dumps(rows, indent=2))
    return rows


def _draft_scores(rules: list[str], row: dict) -> dict | None:
    facts = {"topic": row["topic"], "facts": row["facts"], "quiz": row["quiz"]}
    try:
        lyrics = loop.write_lyrics(facts, playbook=rules or None)
        fit = pipeline.syllable_fit(lyrics)["syllable_fit"]
        covered = loop.fact_coverage(lyrics, facts)["fact_coverage"]
        natural = loop.naturalness(lyrics)["natural"]
    except Exception:
        return None
    return {"fit": fit, "facts": covered, "natural": natural, "score": fit * covered * (0.5 + 0.5 * natural)}


@weave.op
def first_draft_eval(rules: list[str], rows: list[dict], trials: int = GATE_TRIALS) -> dict:
    """Mean first-draft quality over validation pages when the writer follows `rules`."""
    tasks = [row for row in rows for _ in range(trials)]
    with ContextAwareThreadPoolExecutor(max_workers=8) as pool:
        results = [r for r in pool.map(lambda row: _draft_scores(rules, row), tasks) if r]
    mean = lambda key: round(statistics.mean(r[key] for r in results), 3) if results else 0.0
    return {"score": mean("score"), "fit": mean("fit"), "facts": mean("facts"), "natural": mean("natural"),
            "drafts": len(results)}


@weave.op
def propose(playbook: dict, run_evidence: dict) -> dict:
    """Coach step: suggest new rules (and rules to drop) from one run. Nothing is adopted here."""
    final = run_evidence["final"] or {}
    compact = {**run_evidence, "final": {k: final.get(k) for k in ("intelligibility", "fact_coverage", "syllable_fit", "natural", "lyrics")}}
    return loop._chat_json(loop.ANALYST,
        "You coach an AI that writes educational song lyrics to a fixed melody (one syllable per note, strict "
        "per-line syllable budgets). A music model sings the lyrics and a speech recognizer checks each line. "
        "Rules must be general across topics, actionable, under 25 words, and must not trade away syllable fit.",
        f"""Current playbook:
{json.dumps(rules(playbook), indent=1)}

Evidence from the latest song:
{json.dumps(compact, indent=1)}

Propose at most {MAX_CANDIDATES} new rules that would have prevented a failure here, most promising first, and
list any current rules the evidence contradicts. Each proposal will be A/B tested before it is adopted.
Return JSON: {{"candidates": [{{"rule": str, "evidence": short str}}], "remove": [exact rule text]}}""",
        max_tokens=2000, temperature=0.2)


@weave.op
def learn(playbook: dict, run_evidence: dict) -> dict:
    """Propose rules from a run, A/B test each on first drafts, and keep only the ones that help."""
    rows = gate_dataset()
    proposal = propose(playbook, run_evidence)
    current_rules = rules(playbook)
    current = first_draft_eval(current_rules, rows)
    decisions = []

    for candidate in proposal.get("candidates", [])[:MAX_CANDIDATES]:
        trial = first_draft_eval(current_rules + [candidate["rule"]], rows)
        gain = round(trial["score"] - current["score"], 3)
        accepted = gain >= MIN_GAIN and trial["fit"] >= current["fit"] - MAX_FIT_DROP
        decisions.append({"action": "add", "rule": candidate["rule"], "evidence": candidate.get("evidence", ""),
                          "accepted": accepted, "gain": gain, "before": current, "after": trial})
        if accepted:
            current_rules, current = current_rules + [candidate["rule"]], trial

    for rule in proposal.get("remove", []):
        if rule not in current_rules:
            continue
        trial = first_draft_eval([r for r in current_rules if r != rule], rows)
        change = round(trial["score"] - current["score"], 3)
        accepted = change >= -0.005  # dropping a rule is fine if quality holds
        decisions.append({"action": "remove", "rule": rule, "accepted": accepted, "gain": change,
                          "before": current, "after": trial})
        if accepted:
            current_rules, current = [r for r in current_rules if r != rule], trial

    evidence_for = {r["rule"]: r.get("evidence", "") for r in playbook["rules"]}
    evidence_for.update({d["rule"]: d.get("evidence", "") for d in decisions if d["action"] == "add"})
    kept = sum(d["accepted"] for d in decisions)
    return {
        "version": playbook["version"] + 1,
        "rules": [{"rule": r, "evidence": evidence_for.get(r, "")} for r in current_rules][:MAX_RULES],
        "changes": f"{kept} of {len(decisions)} proposals accepted; first-draft score {current['score']}",
        "learned_from": playbook["learned_from"] + [run_evidence["topic"]],
        "decisions": playbook.get("decisions", []) + [{"topic": run_evidence["topic"], "decisions": decisions}],
        "score": current,
    }

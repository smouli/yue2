"""The autonomous loop: source text → facts → lyrics → render → score → rewrite.

Two speeds:
  * text passes (seconds): rewrite lyrics until syllables fit the melody and the facts survive
  * render passes (~1.5 min): sing it, listen with Whisper, feed misheard lines back to the writer

Every step is a Weave op, so each run shows up as one trace tree in the yue2 Weave project.
"""

import json
import os
import re
import time
from pathlib import Path

import openai
import trafilatura
import weave
from weave.trace.util import ContextAwareThreadPoolExecutor

import pipeline

# Gemma 4 31B won the lyric-writer bake-off (best syllable fit and facts taught, ~1.3s per draft).
WRITER = os.environ.get("YUE2_WRITER", "google/gemma-4-31B-it")
ANALYST = "deepseek-ai/DeepSeek-V4-Pro"  # extracts facts, grades quiz answers, quotes source sentences
QUIZ_TAKER = "Qwen/Qwen3-30B-A3B-Instruct-2507"
JUDGE = "Qwen/Qwen3-235B-A22B-Instruct-2507"  # naturalness
# Reasoning models spend completion tokens thinking before they answer; give them room.
REASONING_MODELS = {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "zai-org/GLM-5.2", "zai-org/GLM-5.3-Flash",
                    "moonshotai/Kimi-K2.6", "moonshotai/Kimi-K2.7-Code", "MiniMaxAI/MiniMax-M3",
                    "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B"}
WEAVE_PROJECT = "sanatmouli-scoredata/yue2"
STYLE = (
    "English, sunny laid-back 90s power pop, relaxed male vocal, strummed acoustic guitar, "
    "clean electric guitar, bass, light drums, clear diction, 115 BPM"
)
SECTIONS = [("Verse", 4), ("Chorus", 3)]  # line counts matching pipeline.PHRASE_BUDGET

_client = None


def client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI(
            base_url="https://api.inference.wandb.ai/v1",
            api_key=os.environ["WANDB_API_KEY"],
            project=WEAVE_PROJECT,
            default_headers={"User-Agent": "yue2-hack/0.1"},
        )
    return _client


def _chat_json(model: str, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.7) -> dict:
    extra = {}
    if model in REASONING_MODELS:
        max_tokens = max(max_tokens, 16000)
        if model.startswith("openai/gpt-oss"):
            extra["reasoning_effort"] = "low"
    problem = ""
    for _attempt in range(3):  # models occasionally truncate or wrap their JSON; retry before failing the run
        response = client().chat.completions.create(
            model=model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **extra,
        )
        text = response.choices[0].message.content or ""
        match = re.search(r"\{.*\}", text, re.S)
        try:
            if match:
                return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
        problem = f"finish_reason={response.choices[0].finish_reason}: {text[:300]}"
    raise ValueError(f"{model} returned no valid JSON ({problem})")


@weave.op
def fetch_source(url: str) -> str:
    downloaded = trafilatura.fetch_url(url)
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False) or ""
    return text[:12000]


@weave.op
def extract_facts(source: str, n_facts: int = 6) -> dict:
    return _chat_json(ANALYST,
        "You turn study material into the most important, concrete facts a learner should remember.",
        f"""Source text:
---
{source}
---
Return JSON: {{"topic": str, "facts": [{n_facts} short factual statements],
"quiz": [one question per fact, each {{"question": str, "answer": str}} answerable from that fact alone]}}""")


def _lyrics_text(lines: list[str]) -> str:
    out, i = [], 0
    for name, count in SECTIONS:
        out.append(f"[{name}]")
        out += lines[i:i + count]
        out.append("")
        i += count
    return "\n".join(out).strip()


@weave.op
def write_lyrics(facts: dict, feedback: str | None = None, previous: str | None = None,
                 playbook: list[str] | None = None, locked: dict[int, str] | None = None,
                 model: str | None = None) -> str:
    budget = pipeline.PHRASE_BUDGET
    spec = "\n".join(f"line {i + 1}: exactly {n} syllables" for i, n in enumerate(budget))
    user = f"""Topic: {facts['topic']}
Facts to teach:
{json.dumps(facts['facts'], indent=1)}

Write song lyrics that teach these facts, set to an existing melody. The melody has {len(budget)} phrases,
one lyric line per phrase: lines 1-4 are the verse, lines 5-7 the chorus.
Syllable budget per line (one syllable per note, this is strict):
{spec}
Rules: plain singable English, one fact per line where possible, no filler like "oh yeah",
prefer short common words, avoid tongue-twisters, keep technical terms but place them where they fit.
Write normal whole words. Never split a word into syllables with spaces or hyphens.
"""
    if playbook:
        user += "\nLessons from earlier songs:\n" + "\n".join(f"- {tip}" for tip in playbook)
    if previous:
        user += f"\nPrevious attempt:\n{previous}\n\nWhat went wrong and must be fixed:\n{feedback}\n" \
                "Keep lines that had no problems unchanged."
    if locked:
        user += "\nThese lines were sung clearly and are locked; return them exactly as written:\n" + \
                "\n".join(f"line {i + 1}: {text}" for i, text in sorted(locked.items()))
    user += '\nReturn JSON: {"lines": [7 strings]}'
    lines = _chat_json(model or WRITER, "You are a songwriter who writes precise, singable educational lyrics.", user)["lines"]
    lines = [str(line).strip() for line in lines]
    for i, text in (locked or {}).items():  # enforce locks even if the writer ignored them
        if i < len(lines):
            lines[i] = text
    return _lyrics_text(lines)


def _is_unknown(answer) -> bool:
    text = str(answer or "").strip().lower().strip(".!\"'")
    return text in ("", "unknown", "not stated", "n/a", "none") or text.startswith("unknown")


def _as_bool(value) -> bool:
    """Graders sometimes return "false" strings or {"correct": false} objects; bool() would call those True."""
    if isinstance(value, dict):
        value = value.get("correct", value.get("value", False))
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "correct", "1")
    return value is True or value == 1


@weave.op
def fact_coverage(lyrics: str, facts: dict) -> dict:
    """A separate model answers the quiz from the lyrics alone; the analyst model grades the answers."""
    quiz = facts["quiz"]
    answers = _chat_json(QUIZ_TAKER,
        "You know nothing except the song lyrics you are given. Answer each question using only what the lyrics "
        "state. Do not use outside knowledge. If the lyrics do not state the answer, answer \"unknown\". "
        "Keep each answer under 10 words.",
        f"Lyrics:\n{lyrics}\n\nQuestions:\n" + "\n".join(f"{i + 1}. {q['question']}" for i, q in enumerate(quiz))
        + '\nReturn JSON: {"answers": [one short string per question]}', temperature=0)["answers"]
    answered = [i for i, a in enumerate(answers) if not _is_unknown(a)]
    grades = {}
    if answered:  # "unknown" or blank answers are wrong by rule; only real answers go to the grader
        raw = _chat_json(ANALYST, "You grade quiz answers strictly but accept paraphrases.",
            json.dumps([{"question": quiz[i]["question"], "key": quiz[i]["answer"], "given": answers[i]} for i in answered])
            + '\nReturn JSON: {"correct": [true or false for each item, in order]}', temperature=0)["correct"]
        grades = {i: _as_bool(g) for i, g in zip(answered, raw)}
    items = [{"question": q["question"], "key": q["answer"], "given": a, "correct": grades.get(i, False)}
             for i, (q, a) in enumerate(zip(quiz, answers))]
    return {"fact_coverage": round(sum(i["correct"] for i in items) / max(len(quiz), 1), 3), "items": items}


@weave.op
def align_to_source(lyrics: str, source: str) -> list[dict]:
    """For each lyric line, quote the source sentence it teaches, so a reader can follow along."""
    lines = pipeline.lyric_lines(lyrics)
    quotes = _chat_json(ANALYST,
        "You match song lyrics to the exact sentences of a source text they were based on.",
        f"""Source text:
---
{source}
---
Lyric lines:
{json.dumps(lines, indent=1)}

For each lyric line, copy the single source sentence it best reflects, verbatim, character for character.
Return JSON: {{"sentences": [one string per lyric line]}}""", max_tokens=3000, temperature=0)["sentences"]
    return [{"line": line, "source_sentence": str(quote).strip(), "verbatim": str(quote).strip() in source}
            for line, quote in zip(lines, quotes)]


@weave.op
def naturalness(lyrics: str) -> dict:
    """Fixed judge: does this read like real, singable English rather than compressed shorthand?"""
    lines = pipeline.lyric_lines(lyrics)
    verdict = _chat_json(JUDGE,
        "You judge song lyrics for natural, singable English. Penalize abbreviations (like 'chem'), dropped "
        "articles or verbs, telegraphic shorthand, and awkward word order. Do not judge factual accuracy.",
        "Lyrics (numbered):\n" + "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines))
        + '\nReturn JSON: {"score": integer 1-5 for the whole song, '
          '"awkward_lines": [{"line": line number, "why": short reason}]}',
        temperature=0)
    awkward = [{"line": int(a["line"]), "text": lines[int(a["line"]) - 1], "why": str(a.get("why", ""))}
               for a in verdict.get("awkward_lines", []) if 1 <= int(a.get("line", 0)) <= len(lines)]
    return {"natural": round((int(verdict["score"]) - 1) / 4, 3), "awkward_lines": awkward}


def _text_feedback(fit: dict, coverage: dict) -> str:
    notes = [f"line {i + 1} \"{l['line']}\" has {l['syllables']} syllables, needs exactly {l['notes']}"
             for i, l in enumerate(fit["syllable_lines"]) if l["syllables"] != l["notes"]]
    if not fit["line_count_ok"]:
        notes.append(f"write exactly {len(pipeline.PHRASE_BUDGET)} lines")
    notes += [f"a listener could not answer \"{i['question']}\" (answer: {i['key']})"
              for i in coverage["items"] if not i["correct"]]
    notes += [f"line {a['line']} \"{a['text']}\" reads unnaturally ({a['why']}); use full, natural phrasing"
              for a in coverage.get("awkward_lines", [])]
    taught = [i["key"] for i in coverage["items"] if i["correct"]]
    if taught and notes:
        notes.append("already taught correctly, do not lose these: " + "; ".join(taught))
    return "\n".join(notes)


def _listen_feedback(asr: dict, threshold: float = 0.85) -> str:
    return "\n".join(
        f"line \"{l['line']}\" was heard as \"{l['heard'] or '(nothing)'}\"; reword it with simpler, "
        "clearer words and the same syllable count"
        for l in asr["lines"] if l["score"] < threshold)


@weave.op
def text_pass(facts: dict, feedback: str | None, previous: str | None, playbook: list[str] | None,
              locked: dict[int, str] | None = None) -> dict:
    lyrics = write_lyrics(facts, feedback, previous, playbook, locked)
    fit = pipeline.syllable_fit(lyrics)
    coverage = fact_coverage(lyrics, facts)
    natural = naturalness(lyrics)
    return {"lyrics": lyrics, **fit, **coverage, **natural}


def _draft_score(result: dict) -> float:
    # Naturalness scales the score between 0.5x and 1x so it matters without zeroing out a good fit.
    return result["syllable_fit"] * result["fact_coverage"] * (0.5 + 0.5 * result["natural"])


BASE_SEED = 831001


@weave.op
def render_take(lyrics: str, out_dir: str, seed: int) -> dict:
    """Sing the lyrics once and listen to the result."""
    request = {"id": Path(out_dir).name, "style": STYLE, "lyrics": lyrics, "cot": "melody", "seed": seed}
    rendered = pipeline.render(request, Path(out_dir))
    asr = pipeline.intelligibility(rendered["audio"], rendered["request"])
    worst_line = min(l["score"] for l in asr["lines"])
    return {**rendered, "seed": seed, "intelligibility": asr["intelligibility"], "worst_line": worst_line,
            "take_score": round((asr["intelligibility"] + worst_line) / 2, 3),
            "heard": asr["heard"], "lines": asr["lines"]}


@weave.op
def render_pass(lyrics: str, out_dir: str, takes: int = 1) -> dict:
    """Render `takes` performances in parallel on the GPU and keep the clearest one.

    YuE2 regenerates the whole performance for any lyric change, so a line that was sung clearly
    can come out slurred next time. Extra takes spend spare GPU memory to beat that randomness.
    With takes=1 this is the original single render at the original path and seed.
    """
    if takes == 1:
        candidates = [render_take(lyrics, out_dir, BASE_SEED)]
    else:
        with ContextAwareThreadPoolExecutor(max_workers=takes) as pool:
            candidates = list(pool.map(lambda k: render_take(lyrics, f"{out_dir}/take-{k + 1}", BASE_SEED + k),
                                       range(takes)))
    chosen = max(candidates, key=lambda c: c["take_score"])
    melody = pipeline.melody_fidelity(chosen["audio"])  # guardrail check on the kept take only
    summary = [{"seed": c["seed"], "intelligibility": c["intelligibility"], "worst_line": c["worst_line"],
                "take_score": c["take_score"], "audio": c["audio"], "render_seconds": c["render_seconds"]}
               for c in candidates]
    return {**chosen, **melody, "takes": summary}


@weave.op
def run_loop(url: str, run_name: str, max_text_passes: int = 4, max_render_passes: int = 3,
             fit_target: float = 0.95, coverage_target: float = 0.67, intelligibility_target: float = 0.9,
             line_target: float = 0.85, natural_target: float = 0.5, takes: int = 1,
             playbook: list[str] | None = None, progress_path: str | None = None) -> dict:
    history = []
    started = time.time()

    def log(event: dict):
        history.append({"t": round(time.time(), 1), **event})
        if progress_path:
            Path(progress_path).write_text(json.dumps(history, indent=2))

    source = fetch_source(url)
    facts = extract_facts(source)
    log({"step": "facts", "topic": facts["topic"], "facts": facts["facts"], "url": url, "source": source,
         "writer": WRITER, "playbook": playbook or []})

    lyrics, feedback, best, listen_notes, locked = None, None, None, "", {}
    for r in range(max_render_passes):
        draft = None
        for t in range(max_text_passes):
            result = text_pass(facts, feedback, lyrics, playbook, locked)
            lyrics = result["lyrics"]
            log({"step": "text", "render_pass": r + 1, "text_pass": t + 1, "lyrics": lyrics,
                 "locked_lines": sorted(i + 1 for i in locked), "feedback": feedback,
                 "syllable_fit": result["syllable_fit"], "fact_coverage": result["fact_coverage"],
                 "natural": result["natural"], "awkward_lines": result["awkward_lines"],
                 "syllable_lines": result["syllable_lines"]})
            if draft is None or _draft_score(result) > _draft_score(draft):
                draft = result
            if (result["syllable_fit"] >= fit_target and result["fact_coverage"] >= coverage_target
                    and result["natural"] >= natural_target):
                break
            # Keep the listener's complaints in view while fixing syllables and facts.
            feedback = "\n".join(filter(None, [_text_feedback(result, result), listen_notes]))
        result, lyrics = draft, draft["lyrics"]  # render the best draft, not the last one

        heard = render_pass(lyrics, str(pipeline.HACK / f"runs/{run_name}/render-{r + 1}"), takes)
        log({"step": "render", "render_pass": r + 1, "lyrics": lyrics, "audio": heard["audio"],
             "intelligibility": heard["intelligibility"], "melody_fidelity": heard["melody_fidelity"],
             "syllable_fit": result["syllable_fit"], "fact_coverage": result["fact_coverage"],
             "natural": result["natural"], "lines": heard["lines"], "takes": heard["takes"]})
        score = heard["intelligibility"] * result["fact_coverage"]
        if best is None or score > best["score"]:
            best = {"score": round(score, 3), "render_pass": r + 1, "lyrics": lyrics, "audio": heard["audio"],
                    "intelligibility": heard["intelligibility"], "fact_coverage": result["fact_coverage"],
                    "syllable_fit": result["syllable_fit"], "natural": result["natural"], "lines": heard["lines"]}
        worst_line = min(l["score"] for l in heard["lines"])
        if heard["intelligibility"] >= intelligibility_target and worst_line >= line_target:
            break
        listen_notes = feedback = _listen_feedback(heard, line_target)
        # Lock clearly sung lines so the next rewrite cannot regress them.
        locked = {i: l["line"] for i, l in enumerate(heard["lines"]) if l["score"] >= line_target}

    best["alignment"] = align_to_source(best["lyrics"], source)
    log({"step": "done", "best": best, "seconds": round(time.time() - started, 1)})
    return {"topic": facts["topic"], "best": best, "history": history}

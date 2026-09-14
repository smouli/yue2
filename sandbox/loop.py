"""The autonomous loop: sing a source paragraph's own words to a melody, listen back, and fix what isn't clear.

Two speeds:
  * text passes (seconds): fit the source's words to the melody's phrases with minimal edits
  * render passes (minutes): sing it in several takes, listen with Whisper, feed misheard lines back to the writer

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

import faithful
import melody
import pipeline

# Gemma 4 31B won the lyric-writer bake-off (best syllable fit, ~1.3s per draft).
WRITER = os.environ.get("YUE2_WRITER", "google/gemma-4-31B-it")
ANALYST = "deepseek-ai/DeepSeek-V4-Pro"  # the playbook coach
# Reasoning models spend completion tokens thinking before they answer; give them room.
REASONING_MODELS = {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "zai-org/GLM-5.2", "zai-org/GLM-5.3-Flash",
                    "moonshotai/Kimi-K2.6", "moonshotai/Kimi-K2.7-Code", "MiniMaxAI/MiniMax-M3",
                    "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B"}
WEAVE_PROJECT = "sanatmouli-scoredata/yue2"
STYLE = (
    "English, sunny laid-back 90s power pop, relaxed male vocal, strummed acoustic guitar, "
    "clean electric guitar, bass, light drums, clear diction, 115 BPM"
)

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


def _parse_json(text: str) -> dict | None:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = fenced.group(1) if fenced else text
    match = re.search(r"\{.*\}", body, re.S)
    if not match:
        return None
    for candidate in (match.group(0), re.sub(r",\s*([\]}])", r"\1", match.group(0))):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _chat_json(model: str, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.7) -> dict:
    extra = {}
    if model in REASONING_MODELS:
        max_tokens = max(max_tokens, 16000)
        if model.startswith("openai/gpt-oss"):
            extra["reasoning_effort"] = "low"
    else:
        # Strict JSON mode: Gemma otherwise sometimes wraps invalid JSON in a code fence.
        extra["response_format"] = {"type": "json_object"}
    problem = ""
    for _attempt in range(3):  # retry truncated or malformed JSON before failing the run
        try:
            response = client().chat.completions.create(
                model=model, max_tokens=max_tokens, temperature=temperature,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **extra,
            )
        except openai.BadRequestError:
            if extra.pop("response_format", None) is None:
                raise
            continue  # model doesn't support JSON mode; retry without it
        text = response.choices[0].message.content or ""
        parsed = _parse_json(text)
        if parsed is not None:
            return parsed
        problem = f"finish_reason={response.choices[0].finish_reason}: {text[:300]}"
    raise ValueError(f"{model} returned no valid JSON ({problem})")


@weave.op
def fetch_source(url: str) -> str:
    downloaded = trafilatura.fetch_url(url)
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False) or ""
    return text[:12000]


def page_paragraphs(url: str, min_words: int = 35, max_words: int = 110) -> list[str]:
    """Paragraphs of a page that fit a song, cleaned of citation markers."""
    return [faithful.clean_source(p) for p in fetch_source(url).splitlines() if min_words <= len(p.split()) <= max_words]


BASE_SEED = 831001


@weave.op
def render_take(lyrics: str, out_dir: str, seed: int, abc_file: str, style: str = STYLE) -> dict:
    """Sing the lyrics once and listen to the result."""
    request = {"id": Path(out_dir).name, "style": style, "lyrics": lyrics, "cot": "melody", "seed": seed}
    rendered = pipeline.render(request, Path(out_dir), Path(abc_file))
    asr = pipeline.intelligibility(rendered["audio"], rendered["request"])
    worst_line = min(l["score"] for l in asr["lines"])
    return {**rendered, "seed": seed, "intelligibility": asr["intelligibility"], "worst_line": worst_line,
            "take_score": round((asr["intelligibility"] + worst_line) / 2, 3),
            "heard": asr["heard"], "lines": asr["lines"]}


@weave.op
def render_pass(lyrics: str, out_dir: str, abc_file: str, ranges: list[tuple[float, float]], takes: int = 3,
                seed_offset: int = 0, style: str = STYLE) -> dict:
    """Render `takes` performances in parallel on the GPU and keep the clearest one.

    YuE2 regenerates the whole performance for any lyric change, so a line that was sung clearly
    can come out slurred next time. Extra takes spend spare GPU memory to beat that randomness.
    """
    # A new seed per render pass: if the lyrics come back unchanged, the retry is still a different performance.
    seed = BASE_SEED + seed_offset
    if takes == 1:
        candidates = [render_take(lyrics, out_dir, seed, abc_file, style)]
    else:
        with ContextAwareThreadPoolExecutor(max_workers=takes) as pool:
            candidates = list(pool.map(lambda k: render_take(lyrics, f"{out_dir}/take-{k + 1}", seed + k, abc_file, style),
                                       range(takes)))
    chosen = max(candidates, key=lambda c: c["take_score"])
    melody = pipeline.melody_fidelity(chosen["audio"], ranges)  # guardrail check on the kept take only
    take_summaries = [{"seed": c["seed"], "intelligibility": c["intelligibility"], "worst_line": c["worst_line"],
                "take_score": c["take_score"], "audio": c["audio"], "render_seconds": c["render_seconds"]}
               for c in candidates]
    return {**chosen, **melody, "takes": take_summaries}


SYLLABLE_TOLERANCE = 1
# Dense source text garbles at the song's 115 BPM; at 90 BPM clarity rose from 0.17 to 0.52 on the same lyrics.
FAITHFUL_BPM = 90
FILLER_SHARE = 0.85  # rough share of syllables left after dropping filler words; sizes the song


def song_plan(source: str) -> dict:
    """Which verses and choruses the paragraph needs, and one syllable budget per lyric line."""
    profile = melody.load_profile()
    needed = round(melody.count_text_syllables(source) * FILLER_SHARE)
    if needed > melody.capacity(profile):
        raise ValueError(f"Paragraph needs ~{needed} syllables; the melody holds {melody.capacity(profile)}. "
                         "Use a shorter paragraph.")
    chosen = melody.plan_song(profile, needed)
    return {"profile": profile, "chosen": chosen, "needed": needed,
            "sections": [{"name": s.name, "phrases": s.phrases} for s in chosen]}


@weave.op
def write_faithful(source: str, sections: list[dict], feedback: str | None = None, previous: str | None = None,
                   playbook: list[str] | None = None, locked: dict[int, str] | None = None,
                   model: str | None = None, temperature: float = 0.7) -> str:
    budget = [n for s in sections for n in s["phrases"]]
    layout = []
    line_no = 0
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
{chr(10).join(layout)}
"""
    if playbook:
        user += "\nLessons from earlier songs:\n" + "\n".join(f"- {tip}" for tip in playbook)
    if previous:
        user += f"\nPrevious attempt:\n{previous}\n\nWhat went wrong and must be fixed:\n{feedback}\n" \
                "Keep lines that had no problems unchanged."
    if locked:
        user += "\nThese lines were sung clearly and are locked; return them exactly as written:\n" + \
                "\n".join(f"line {i + 1}: {text}" for i, text in sorted(locked.items()))
    user += f'\nReturn JSON: {{"lines": [{len(budget)} strings]}}'
    lines = _chat_json(model or WRITER, "You set existing text to music with minimal, faithful edits.", user,
                       max_tokens=4000, temperature=temperature)["lines"]
    lines = [str(line).strip() for line in lines][:len(budget)]
    lines += [""] * (len(budget) - len(lines))
    for i, text in (locked or {}).items():
        if i < len(lines):
            lines[i] = text
    out, k = [], 0
    for s in sections:
        out.append(f"[{s['name'].capitalize()}]")
        out += lines[k:k + len(s["phrases"])]
        out.append("")
        k += len(s["phrases"])
    return "\n".join(out).strip()


@weave.op
def faithful_text_pass(source: str, sections: list[dict], feedback: str | None, previous: str | None,
                       playbook: list[str] | None, locked: dict[int, str] | None = None) -> dict:
    lyrics = write_faithful(source, sections, feedback, previous, playbook, locked)
    budget = [n for s in sections for n in s["phrases"]]
    fit = pipeline.syllable_fit(lyrics, budget, tolerance=SYLLABLE_TOLERANCE)
    fidelity = faithful.score(source, pipeline.lyric_lines(lyrics))
    return {"lyrics": lyrics, **fit, **{k: v for k, v in fidelity.items() if k not in ("source_spans", "source_words")}}


def _faithful_feedback(result: dict) -> str:
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


def _faithful_listen_feedback(asr: dict, threshold: float = 0.85) -> str:
    """Misheard lines, with fixes faithful mode allows (the writer must not reword the source)."""
    misheard = [f"line \"{l['line']}\" was heard as \"{l['heard'] or '(nothing)'}\""
                for l in asr["lines"] if l["score"] < threshold]
    if not misheard:
        return ""
    return "\n".join(misheard) + (
        "\nMake these lines clearer without changing the source's words: give long or technical words more room "
        "by moving a word to a neighbouring line, drop filler words, put a hard term at the start of its line, "
        "write acronyms and symbols as they are spoken (A T P, C O two), and avoid packing several hard terms into one line.")


@weave.op
def run_faithful(source: str, run_name: str, url: str = "", max_text_passes: int = 4, max_render_passes: int = 3,
                 fit_target: float = 0.9, faithful_target: float = 0.85, intelligibility_target: float = 0.9,
                 line_target: float = 0.85, takes: int = 3, bpm: int = FAITHFUL_BPM,
                 playbook: list[str] | None = None, progress_path: str | None = None) -> dict:
    history = []
    started = time.time()
    source = faithful.clean_source(source)

    def log(event: dict):
        history.append({"t": round(time.time(), 1), **event})
        if progress_path:
            Path(progress_path).write_text(json.dumps(history, indent=2))

    plan = song_plan(source)
    sections, needed, chosen = plan["sections"], plan["needed"], plan["chosen"]
    abc_file = str(melody.write_abc(plan["profile"], chosen, pipeline.HACK / f"runs/{run_name}/melody.abc", bpm))
    style = re.sub(r"\d+ BPM", f"{bpm} BPM, unhurried phrasing, every word clearly enunciated", STYLE)
    ranges = melody.source_ranges(chosen)
    page = url.rstrip("/").rsplit("/", 1)[-1].replace("_", " ") if url else ""
    opening = " ".join(source.split()[:8])
    title = f"{page}: “{opening}…”" if page else f"“{opening}…”"
    log({"step": "setup", "topic": title, "url": url, "source": source,
         "sections": sections, "syllables_needed": needed, "bpm": bpm, "writer": WRITER, "playbook": playbook or []})

    lyrics, feedback, best, listen_notes, locked = None, None, None, "", {}
    result = None
    for r in range(max_render_passes):
        draft = None
        for t in range(max_text_passes):
            result = faithful_text_pass(source, sections, feedback, lyrics, playbook, locked)
            lyrics = result["lyrics"]
            log({"step": "text", "render_pass": r + 1, "text_pass": t + 1, "lyrics": lyrics,
                 "locked_lines": sorted(i + 1 for i in locked), "feedback": feedback,
                 "syllable_fit": result["syllable_fit"], "faithfulness": result["faithfulness"],
                 "kept": result["kept"], "no_additions": result["no_additions"],
                 "dropped_words": result["dropped_words"], "added_words": result["added_words"],
                 "syllable_lines": result["syllable_lines"]})
            if draft is None or result["syllable_fit"] * result["faithfulness"] > draft["syllable_fit"] * draft["faithfulness"]:
                draft = result
            if result["syllable_fit"] >= fit_target and result["faithfulness"] >= faithful_target:
                break
            feedback = "\n".join(filter(None, [_faithful_feedback(result), listen_notes]))
        result, lyrics = draft, draft["lyrics"]

        heard = render_pass(lyrics, str(pipeline.HACK / f"runs/{run_name}/render-{r + 1}"), abc_file, ranges, takes,
                            seed_offset=100 * r, style=style)
        log({"step": "render", "render_pass": r + 1, "lyrics": lyrics, "audio": heard["audio"],
             "intelligibility": heard["intelligibility"], "melody_fidelity": heard["melody_fidelity"],
             "syllable_fit": result["syllable_fit"], "faithfulness": result["faithfulness"],
             "lines": heard["lines"], "takes": heard["takes"]})
        score = heard["intelligibility"] * result["faithfulness"]
        if best is None or score > best["score"]:
            best = {"score": round(score, 3), "render_pass": r + 1, "lyrics": lyrics, "audio": heard["audio"],
                    "intelligibility": heard["intelligibility"], "faithfulness": result["faithfulness"],
                    "syllable_fit": result["syllable_fit"],
                    "lines": heard["lines"]}
        worst_line = min(l["score"] for l in heard["lines"])
        if heard["intelligibility"] >= intelligibility_target and worst_line >= line_target:
            break
        listen_notes = feedback = _faithful_listen_feedback(heard, line_target)
        locked = {i: l["line"] for i, l in enumerate(heard["lines"]) if l["score"] >= line_target}

    final = faithful.score(source, pipeline.lyric_lines(best["lyrics"]))
    best["source_words"] = final["source_words"]
    best["source_spans"] = faithful.display_spans(source, final["source_spans"])
    log({"step": "done", "best": best, "seconds": round(time.time() - started, 1)})
    return {"topic": title, "best": best, "history": history}

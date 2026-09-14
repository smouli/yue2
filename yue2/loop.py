"""The loop: sing a paragraph's own words to a melody, listen back, and fix what isn't clear.

Two speeds:
  * text passes (seconds): fit the source's words to the melody's lines with minimal edits
  * render passes (minutes): sing several takes, listen with Whisper, feed misheard lines back to the writer

The loop is storage- and database-agnostic: it writes working files under `workdir`, saves every take through
`storage` as soon as it is sung, and reports progress through `emit(event)`.
"""

import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from yue2 import melody, tracing, writer
from yue2.text import faithful
from yue2.text.syllables import count_text_syllables, lyric_lines, syllable_fit

STYLE = ("English, sunny laid-back 90s power pop, relaxed male vocal, strummed acoustic guitar, "
         "clean electric guitar, bass, light drums, {bpm} BPM, unhurried phrasing, every word clearly enunciated")
FILLER_SHARE = 0.85  # rough share of syllables left after dropping filler words; sizes the song
BASE_SEED = 831001
MIN_WORDS, MAX_WORDS = 20, 220

try:  # keep Weave's trace context across the parallel takes
    from weave.trace.util import ContextAwareThreadPoolExecutor as TakePool
except ImportError:
    TakePool = ThreadPoolExecutor


class ParagraphError(ValueError):
    """The paragraph can't be sung (too short, too long for the melody)."""


def song_plan(source: str, profile: dict) -> dict:
    """Which verses and choruses the paragraph needs, and one syllable budget per lyric line."""
    words = len(source.split())
    if words < MIN_WORDS:
        raise ParagraphError(f"Paragraph has {words} words; use at least {MIN_WORDS}.")
    needed = round(count_text_syllables(source) * FILLER_SHARE)
    if needed > melody.capacity(profile):
        raise ParagraphError(f"Paragraph needs ~{needed} syllables; the melody holds {melody.capacity(profile)}. "
                             "Use a shorter paragraph.")
    chosen = melody.plan_song(profile, needed)
    return {"chosen": chosen, "needed": needed, "sections": [{"name": s.name, "phrases": s.phrases} for s in chosen]}


@tracing.op
def text_pass(write, source: str, sections: list[dict], feedback: str | None, previous: str | None,
              playbook: list[str] | None, locked: dict[int, str]) -> dict:
    lyrics = write(source=source, sections=sections, feedback=feedback, previous=previous, playbook=playbook, locked=locked)
    budget = [n for s in sections for n in s["phrases"]]
    fit = syllable_fit(lyrics, budget, tolerance=writer.SYLLABLE_TOLERANCE)
    fidelity = faithful.score(source, lyric_lines(lyrics))
    return {"lyrics": lyrics, **fit, **{k: v for k, v in fidelity.items() if k not in ("source_spans", "source_words")}}


@tracing.op
def render_take(models, lyrics: str, style: str, abc_path: str, seed: int, out_dir: str) -> dict:
    sung = models.sing(lyrics, style, Path(abc_path), seed, Path(out_dir))
    heard = models.listen(Path(sung["audio"]), Path(sung["request"]))
    worst_line = min((l["score"] for l in heard["lines"]), default=0.0)
    return {**sung, "seed": seed, "intelligibility": heard["intelligibility"], "worst_line": worst_line,
            "take_score": round((heard["intelligibility"] + worst_line) / 2, 3), "lines": heard["lines"]}


def _to_mp3(audio: Path) -> Path:
    if not shutil.which("ffmpeg"):
        return audio
    mp3 = audio.with_suffix(".mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio), "-b:a", "160k", str(mp3)], check=True)
    return mp3


@tracing.op
def run_song(job_id: str, source: str, *, settings, models, storage, emit, llm=None, url: str = "",
             takes: int | None = None, playbook: list[str] | None = None, max_text_passes: int = 4,
             max_render_passes: int = 3, fit_target: float = 0.9, faithful_target: float = 0.85,
             clarity_target: float = 0.9, line_target: float = 0.85) -> dict:
    started = time.time()
    takes = takes or settings.takes
    workdir = settings.home / "work" / job_id
    source = faithful.clean_source(source)
    profile = melody.load_profile(settings.melody_dir)
    plan = song_plan(source, profile)
    sections, chosen = plan["sections"], plan["chosen"]
    abc_path = str(melody.write_abc(profile, chosen, workdir / "melody.abc", settings.bpm))
    source_pitches = melody.section_pitches(profile, chosen)
    style = STYLE.format(bpm=settings.bpm)

    if llm is None:
        write = writer.fake_write
    else:
        write = lambda **kw: writer.write(llm, settings.writer_model, **kw)

    page = url.rstrip("/").rsplit("/", 1)[-1].replace("_", " ") if url else ""
    opening = " ".join(source.split()[:8])
    title = f"{page}: “{opening}…”" if page else f"“{opening}…”"
    emit({"step": "setup", "topic": title, "url": url, "source": source, "sections": sections,
          "syllables_needed": plan["needed"], "bpm": settings.bpm, "takes": takes,
          "writer": "fake" if llm is None else settings.writer_model, "playbook": playbook or []})

    lyrics, feedback, best, listen_notes, locked = None, None, None, "", {}
    for r in range(max_render_passes):
        draft = None
        for t in range(max_text_passes):
            result = text_pass(write, source, sections, feedback, lyrics, playbook, locked)
            lyrics = result["lyrics"]
            emit({"step": "text", "render_pass": r + 1, "text_pass": t + 1, "lyrics": lyrics,
                  "locked_lines": sorted(i + 1 for i in locked), "feedback": feedback,
                  "syllable_fit": result["syllable_fit"], "faithfulness": result["faithfulness"],
                  "kept": result["kept"], "no_additions": result["no_additions"],
                  "dropped_words": result["dropped_words"], "added_words": result["added_words"],
                  "syllable_lines": result["syllable_lines"]})
            if draft is None or result["syllable_fit"] * result["faithfulness"] > draft["syllable_fit"] * draft["faithfulness"]:
                draft = result
            if result["syllable_fit"] >= fit_target and result["faithfulness"] >= faithful_target:
                break
            feedback = "\n".join(filter(None, [writer.text_feedback(result), listen_notes]))
        result, lyrics = draft, draft["lyrics"]

        # New seeds each pass: if the lyrics come back unchanged, the retry is still a different performance.
        seed = BASE_SEED + 100 * r
        pass_dir = workdir / f"render-{r + 1}"
        with TakePool(max_workers=takes) as pool:
            candidates = list(pool.map(
                lambda k: render_take(models, lyrics, style, abc_path, seed + k, str(pass_dir / f"take-{k + 1}")),
                range(takes)))
        for k, c in enumerate(candidates):  # keep every take, even if this machine goes away
            c["audio_key"] = storage.put(Path(c["audio"]), f"songs/{job_id}/render-{r + 1}/take-{k + 1}{Path(c['audio']).suffix}")
        chosen_take = max(candidates, key=lambda c: c["take_score"])
        check = models.melody_check(Path(chosen_take["audio"]), source_pitches)

        emit({"step": "render", "render_pass": r + 1, "lyrics": lyrics, "audio_key": chosen_take["audio_key"],
              "intelligibility": chosen_take["intelligibility"], "melody_fidelity": check["melody_fidelity"],
              "syllable_fit": result["syllable_fit"], "faithfulness": result["faithfulness"], "lines": chosen_take["lines"],
              "takes": [{"seed": c["seed"], "intelligibility": c["intelligibility"], "worst_line": c["worst_line"],
                         "take_score": c["take_score"], "audio_key": c["audio_key"], "render_seconds": c["render_seconds"]}
                        for c in candidates]})
        score = chosen_take["intelligibility"] * result["faithfulness"]
        if best is None or score > best["score"]:
            best = {"score": round(score, 3), "render_pass": r + 1, "lyrics": lyrics, "audio": chosen_take["audio"],
                    "intelligibility": chosen_take["intelligibility"], "faithfulness": result["faithfulness"],
                    "syllable_fit": result["syllable_fit"], "lines": chosen_take["lines"]}
        if chosen_take["intelligibility"] >= clarity_target and chosen_take["worst_line"] >= line_target:
            break
        listen_notes = feedback = writer.listen_feedback(chosen_take["lines"], line_target)
        locked = {i: l["line"] for i, l in enumerate(chosen_take["lines"]) if l["score"] >= line_target}

    song = _to_mp3(Path(best.pop("audio")))
    best["audio_key"] = storage.put(song, f"songs/{job_id}/song{song.suffix}")
    final = faithful.score(source, lyric_lines(best["lyrics"]))
    best["source_words"] = final["source_words"]
    best["source_spans"] = faithful.display_spans(source, final["source_spans"])
    done = {"step": "done", "best": best, "seconds": round(time.time() - started, 1)}
    emit(done)
    return done

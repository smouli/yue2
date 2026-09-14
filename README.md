# yue2: listen to what you read

We're building an app to make and remix music. The question here: can it sing what you're reading?

Give it a paragraph from a web page or textbook. An autonomous loop sets the paragraph's own words to an
existing melody (the demo uses *Island in the Sun* by Weezer), sings it, listens back, and rewrites whatever
it can't hear clearly, until the song is clear, faithful to the text and fits the tune. Across songs, it
proposes rules for itself and keeps only the ones that win an A/B test.

**Traces and evaluations:** [Weave project](https://wandb.ai/sanatmouli-scoredata/yue2/weave).

## The loop

```
paragraph ──► TEXT PASSES (seconds, up to 4)
              Gemma 4 31B fits the source's words to the melody's phrases
              score: syllable fit · faithful to the text  ──► feedback ──► rewrite
                        │ best draft
              RENDER PASSES (minutes, up to 3)
              YuE2 sings 3 takes in parallel (new seeds each pass) on a GPU worker
              Whisper checks every line; keep the clearest take; SheetSage2 melody guardrail
              lock clear lines ──► send misheard lines back with what was heard
                        │ best pass (heard clearly × faithful)
              karaoke player: song lines and the source words highlight as they're sung

across songs: coach proposes rules ──► A/B test on 40 first drafts from 8 new pages ──► keep if it helps
```

The writer sings the paragraph itself. Allowed edits: split sentences at pauses, drop filler words,
contractions, numbers and symbols written out as spoken; never paraphrase.

## Scoring rubric

![How each score is computed](docs/scoring-pipeline.svg)

![Scoring rubric](docs/rubric.png)

| Score | How it's measured | Target | What the loop does with it |
|---|---|---|---|
| **Heard clearly** | Whisper transcribes the take; each line compared letter by letter, numbers spelled out on both sides | song ≥ 90%, every line ≥ 85% | stop; lock clear lines; feed back misheard lines |
| **Faithful to the text** | Source content words matched in order (LCS), F2 of kept vs. added | ≥ 85% | stop rewriting text |
| **Syllable fit** | CMU-dictionary syllables vs. notes per melody phrase, ±1 | ≥ 90% | stop rewriting text; line-level feedback |
| **Melody check** | SheetSage2 re-transcribes the take; notes vs. the original | guardrail | reported only |

Best of 3 takes = mean of song clarity and its worst line. Best pass = heard clearly × faithful. None of these
scores is graded by an LLM.

## Results

| What | Result |
|---|---|
| Scorer control test (fitted / medium / overstuffed lyrics) | heard clearly 1.00 → 0.28 → 0.00; melody check stays 0.96–0.99, so it is a guardrail, not a lyric signal |
| Faithfulness score sanity check | light trim 1.00, synonyms 0.67, paraphrase 0.08 |
| Faithful mode, Calvin cycle paragraph | heard clearly 0.17 at 115 BPM → 0.76 after 90 BPM, new seeds per pass and faithful feedback (faithfulness 0.81) |
| Faithful mode, Industrial Revolution paragraph | heard clearly 0.63 → 0.80 over 3 passes, faithfulness 0.88 |
| Tempo diagnostic, same lyrics | 115 BPM 0.17, 90 BPM 0.52 |
| Take variance, same lyrics | 0.22 to 0.81 across seeds |

### Bugs the evaluations caught
- **Rewrites undid earlier fixes** when every pass rewrote the whole song. Fixed by locking clear lines and
  rendering the best draft, not the last.
- **Faithful mode got stuck**: the listener asked to reword, faithful rules forbid it, and the same seed rendered
  the same song. Fixed with new seeds per pass and feedback that respects faithfulness.

### Not finished
- **The playbook and bake-off live only in `molab/`.** The `yue2` package and web app run the loop without learned
  rules for now.
- **The playbook experiments need a rerun.** The earlier runs scored rules with a fact-quiz mode that has since been
  removed; the rule A/B tests now use syllable fit and faithfulness, and have not been run yet.
- **The writer bake-off needs a rerun** on faithful-mode scores; Gemma 4 31B was chosen under the old scores.
- **No model weights were trained.** The loop learns rules, not parameters. Next step: fine-tune a small writer
  on the loop's best lyrics and serve it as a LoRA on W&B Inference.

## Run it

**On a laptop, no GPU.** Fake models stand in for the singer and listener, so the whole flow (submit, live
passes, sing-along player) runs in a couple of seconds per song:

```bash
docker compose up --build
```

Open http://localhost:8080. Add `LLM_API_KEY` to `.env` (from [`.env.example`](.env.example)) to use a real lyric
writer; without one a simple no-LLM writer fills the lines.

**On a GPU.** The worker runs YuE2, Whisper and SheetSage2, each in its own environment:

```bash
docker compose -f compose.yml -f compose.gpu.yml up -d --build
```

**On DigitalOcean.** One GPU Droplet with a bootstrap script, plus Serverless Inference for the writer and
Spaces for storage: [deploy/digitalocean](deploy/digitalocean/README.md).

**On Modal or CoreWeave sandboxes.** A dispatcher starts one GPU sandbox per song, so you pay only while songs
are being made: [deploy/sandboxes](deploy/sandboxes/README.md).

**Tests:**

```bash
uv run --no-project --python 3.12 --with-editable . --with pytest --with httpx pytest
```

Queue tests need Postgres (`DATABASE_URL`) and skip without it.

## How it's built

```
web (FastAPI + UI) ──► Postgres: songs, progress events, job queue ◄── worker(s) ──► writer API
        │                                                  ◄── or dispatcher ──► a sandbox per song
        └────────────── storage: local folder or S3-compatible bucket ◄───┘
```

- **Settings come from the environment** ([yue2/config.py](yue2/config.py)), so the same images run on a laptop,
  a GPU VM or a container platform.
- **The queue is Postgres** (`FOR UPDATE SKIP LOCKED`, heartbeats, retry of abandoned songs): add workers on any
  machine that can reach the database and storage.
- **Always-on or per song:** a worker claims songs itself; the dispatcher hands each song to a runner (Modal,
  CoreWeave, or local processes). Runner jobs report to the web API with a per-song token.
- **Every take is saved as soon as it's sung**, and every loop step is a progress event the UI polls.
- **Weave tracing** is on when `WEAVE_PROJECT` is set.

## Layout

| Path | What |
|---|---|
| `yue2/loop.py` | the loop: song plan, text passes, render passes, best-of-N takes |
| `yue2/writer.py`, `yue2/llm.py` | lyric writer prompt and feedback; any OpenAI-compatible endpoint |
| `yue2/text/` | syllable fit and faithfulness scores, source-word spans for the sing-along |
| `yue2/melody.py` | melody profile: sections and phrases from the transcription; tempo control |
| `yue2/models/` | YuE2, Whisper and SheetSage2 behind one interface (`local`), and stand-ins (`fake`) |
| `yue2/db.py`, `yue2/worker.py` | Postgres job queue; the worker, and `run-song` for one song in a job |
| `yue2/dispatcher.py`, `yue2/runners/` | one-off jobs per song on Modal, CoreWeave or local processes |
| `yue2/report.py` | where progress goes: Postgres, or the web API with a per-song token |
| `yue2/api/` | FastAPI app and the single-page UI |
| `yue2/storage.py` | local folder or S3-compatible storage |
| `Dockerfile`, `docker/worker-gpu.Dockerfile`, `compose*.yml` | images and the Compose stack |
| `deploy/digitalocean/` | GPU Droplet guide and bootstrap script |
| `deploy/sandboxes/` | Modal and CoreWeave sandbox guide |
| `tests/` | scores, melody plan, fake end-to-end loop, queue, API, runners and dispatcher |
| `molab/` | the original marimo notebooks and sandbox scripts, including the playbook and writer bake-off experiments |
| `tools/video/` | demo video renderer |
| `docs/` | scoring diagram and rubric |

## Licenses and rights

- This repo has no license file yet, so the code is all rights reserved by default. YuE2's code is Apache 2.0.
- **YuE2 and SheetSage2 weights are CC BY-NC 4.0**: noncommercial use only.
- The demo sets new lyrics to the melody of *Island in the Sun* (Weezer) for a noncommercial demo. The
  original recording is not distributed; audio files and transcribed scores of it are gitignored.

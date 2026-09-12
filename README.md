# yue2 — listen to what you read

CoreWeave Hacks project (Sep 2026). An autonomous loop that turns a webpage or textbook
section into a song set to an existing melody, then checks and rewrites its own output until
the song is faithful to the source, singable, and intelligible.

## How it works

```
source text → key facts → lyrics fitted to the melody's syllable budget
      ↑                                   ↓
rewrite weak lines ← scorers ← YuE2 render (cot="melody", transcribed melody ABC)
                     melody fidelity · intelligibility · syllable fit · fact coverage
```

- **YuE2-3B** renders new lyrics over a melody score.
- **SheetSage2** transcribes the source track into a melody score, and re-transcribes each
  render to verify it still follows that melody.
- **W&B Inference** serves the LLMs: DeepSeek-V4-Pro writes and grades lyrics, Qwen3-30B takes
  the fact quiz.
- **W&B Weave** traces every loop run: each step is a `weave.op`, and inference calls are traced
  with their token usage. Traces: [sanatmouli-scoredata/yue2](https://wandb.ai/sanatmouli-scoredata/yue2/weave).
- **molab** (marimo on CoreWeave) hosts the GPU notebook and the demo UI.

## Status

| Step | Result |
|---|---|
| YuE2 smoke test | 59s of audio in 30s, 9 GB VRAM peak (RTX PRO 6000 Blackwell) |
| Source melody transcription | 24s, no warnings; verse phrases 7/7/7/7 notes |
| Cover render, verse + chorus | 40s of audio in 18s |
| Melody fidelity of cover | 97.4% pitch-sequence match against the source |
| Intelligibility (Whisper large-v3) | 100% of words heard correctly on cover v1 |
| Control test: medium / bad lyrics | intelligibility 1.00 → 0.28 → 0.00; syllable fit 1.00 → 0.79 → 0.39; melody fidelity 0.97 → 0.99 → 0.96 (guardrail only) |
| Loop run 3 (black holes) | intelligibility 0.88 → 0.96 across render passes at 100% fact coverage; traced in Weave |
| Loop run, photosynthesis (3 takes) | one Weave trace: 17 W&B Inference calls (~11k tokens), 5 text passes, 9 takes rendered |

## Layout

| Path | What |
|---|---|
| `notebook.py` | molab notebook (edited live through `marimo pair`); the demo UI is at the top |
| `sandbox/loop.py` | the loop: facts, lyric passes, render passes with best-of-N takes, source alignment |
| `sandbox/singalong.py` | sing-along player widget: highlights the sung line and its source sentence |
| `sandbox/setup.sh` | one-time install on the molab sandbox |
| `sandbox/transcribe.sh` | SheetSage2 transcription of the source track |
| `sandbox/asr_score.py` | intelligibility scorer: Whisper transcript vs intended lyrics, per line |
| `requests/` | YuE2 song requests (style + lyrics) |

Audio files and transcribed scores of the source track are gitignored and not distributed.

## Demo

In the notebook, paste a URL and press **Make the song**. Progress cards show each render pass
(heard clearly, facts taught, syllable fit, and every take). When the loop finishes, the player
highlights each lyric line as it is sung next to the source sentence it teaches.

## Setup

1. Open a notebook on [molab](https://molab.marimo.io/), attach the GPU, and choose **Pair with an agent**.
2. `cp .env.example .env` and fill in `WANDB_API_KEY` and `MARIMO_TOKEN`.
3. Run `sandbox/setup.sh` on the sandbox (detached; about 10 minutes).

molab sets `PYTHONSAFEPATH=1` and a kernel `PYTHONPATH` that leak into subprocess venvs; run
sandbox scripts with `env -u PYTHONPATH -u PYTHONSAFEPATH`.

## Licenses

YuE2 and SheetSage2 weights are CC BY-NC 4.0: noncommercial use only.

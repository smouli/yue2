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
- **Weave** traces every loop pass and scorer (planned).
- **molab** (marimo on CoreWeave) hosts the GPU notebook and the demo UI.

## Status

| Step | Result |
|---|---|
| YuE2 smoke test | 59s of audio in 30s, 9 GB VRAM peak (RTX PRO 6000 Blackwell) |
| Source melody transcription | 24s, no warnings; verse phrases 7/7/7/7 notes |
| Cover render, verse + chorus | 40s of audio in 18s |
| Melody fidelity of cover | 97.4% pitch-sequence match against the source |
| Intelligibility (Whisper) | next |
| Weave tracing | next |

## Layout

| Path | What |
|---|---|
| `notebook.py` | molab notebook (edited live through `marimo pair`) |
| `sandbox/setup.sh` | one-time install on the molab sandbox |
| `sandbox/transcribe.sh` | SheetSage2 transcription of the source track |
| `requests/` | YuE2 song requests (style + lyrics) |

Audio files and transcribed scores of the source track are gitignored and not distributed.

## Setup

1. Open a notebook on [molab](https://molab.marimo.io/), attach the GPU, and choose **Pair with an agent**.
2. `cp .env.example .env` and fill in `WANDB_API_KEY` and `MARIMO_TOKEN`.
3. Run `sandbox/setup.sh` on the sandbox (detached; about 10 minutes).

molab sets `PYTHONSAFEPATH=1`, which breaks the YuE2 skill scripts' sibling imports; run
them with `env -u PYTHONSAFEPATH`.

## Licenses

YuE2 and SheetSage2 weights are CC BY-NC 4.0: noncommercial use only.

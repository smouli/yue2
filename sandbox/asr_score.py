"""Intelligibility scorer: transcribe a render with Whisper and score each intended lyric line.

Run in the ASR venv:
    .venv-asr/bin/python asr_score.py audio.flac request.json --output asr.json
"""

import argparse
import difflib
import json
import re
from pathlib import Path

import torch
from transformers import pipeline

MODEL = "openai/whisper-large-v3"


def normalize(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def lyric_lines(lyrics: str) -> list[str]:
    return [line.strip() for line in lyrics.splitlines() if line.strip() and not line.strip().startswith("[")]


def score_lines(lines: list[str], heard: str) -> list[dict]:
    """Align the heard words to the concatenated reference, then attribute errors to each line."""
    ref_words, owner = [], []
    for i, line in enumerate(lines):
        words = normalize(line)
        ref_words += words
        owner += [i] * len(words)
    hyp_words = normalize(heard)

    errors = [0] * len(lines)
    heard_by_line = [[] for _ in lines]
    matcher = difflib.SequenceMatcher(None, ref_words, hyp_words, autojunk=False)
    for tag, r1, r2, h1, h2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(r2 - r1):
                heard_by_line[owner[r1 + k]].append(hyp_words[h1 + k])
            continue
        if r1 == r2:  # insertion: charge it to the neighbouring reference line
            line = owner[min(r1, len(owner) - 1)]
            errors[line] += h2 - h1
            heard_by_line[line] += hyp_words[h1:h2]
            continue
        for k in range(r1, r2):
            errors[owner[k]] += 1
        extra = max(0, (h2 - h1) - (r2 - r1))
        errors[owner[r2 - 1]] += extra
        heard_by_line[owner[r1]] += hyp_words[h1:h2]

    results = []
    for i, line in enumerate(lines):
        n = len(normalize(line))
        heard_line = " ".join(heard_by_line[i])
        results.append({
            "line": line,
            "heard": heard_line,
            "wer": round(min(1.0, errors[i] / max(n, 1)), 3),
            # Letter-level similarity forgives word-boundary slips like "up on" vs "upon".
            "score": round(letter_similarity(line, heard_line), 3),
        })
    return results


def letter_similarity(reference: str, heard: str) -> float:
    ref, hyp = "".join(normalize(reference)), "".join(normalize(heard))
    if not ref:
        return 1.0
    matched = sum(block.size for block in difflib.SequenceMatcher(None, ref, hyp, autojunk=False).get_matching_blocks())
    return matched / max(len(ref), len(hyp))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("request")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    lyrics = json.loads(Path(args.request).read_text())["lyrics"]
    lines = lyric_lines(lyrics)

    asr = pipeline(
        "automatic-speech-recognition", model=MODEL,
        torch_dtype=torch.bfloat16, device="cuda:0",
    )
    heard = asr(args.audio, return_timestamps=True, generate_kwargs={"language": "english"})["text"].strip()

    per_line = score_lines(lines, heard)
    weights = [len("".join(normalize(r["line"]))) for r in per_line]
    total = max(sum(weights), 1)
    result = {
        "model": MODEL,
        "heard": heard,
        "wer": round(sum(r["wer"] * w for r, w in zip(per_line, weights)) / total, 3),
        "intelligibility": round(sum(r["score"] * w for r, w in zip(per_line, weights)) / total, 3),
        "lines": per_line,
    }
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

"""Weave Evaluation: which open-weight model on W&B Inference writes the best lyrics for the loop?

Every candidate writes a first draft for the same topics; fixed scorers judge the drafts.
    python bakeoff.py [model ...]   # updates runs/bakeoff.json; one comparable evaluation per model in Weave
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import weave

import loop
import pipeline

URLS = [
    "https://en.wikipedia.org/wiki/Photosynthesis",
    "https://en.wikipedia.org/wiki/Black_hole",
    "https://en.wikipedia.org/wiki/French_Revolution",
]
CANDIDATES = [
    "deepseek-ai/DeepSeek-V4-Pro",
    "deepseek-ai/DeepSeek-V4-Flash",
    "openai/gpt-oss-120b",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "meta-llama/Llama-3.3-70B-Instruct",
    "MiniMaxAI/MiniMax-M3",
    "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B",
    "zai-org/GLM-5.2",
    "moonshotai/Kimi-K2.6",
    "google/gemma-4-31B-it",
]
JUDGE = "Qwen/Qwen3-235B-A22B-Instruct-2507"
DATASET_PATH = pipeline.HACK / "runs/bakeoff-dataset.json"


class LyricWriter(weave.Model):
    model_name: str

    @weave.op
    def predict(self, topic: str, facts: list[str], quiz: list[dict]) -> dict:
        start = time.time()
        try:
            lyrics = loop.write_lyrics({"topic": topic, "facts": facts, "quiz": quiz}, model=self.model_name)
            return {"lyrics": lyrics, "seconds": round(time.time() - start, 1), "error": None}
        except Exception as error:
            return {"lyrics": None, "seconds": round(time.time() - start, 1), "error": f"{type(error).__name__}: {error}"[:300]}


@weave.op
def syllable_fit(output: dict) -> dict:
    if not output["lyrics"]:
        return {"valid": False, "fit": 0.0}
    result = pipeline.syllable_fit(output["lyrics"])
    return {"valid": result["line_count_ok"], "fit": result["syllable_fit"]}


@weave.op
def facts_taught(output: dict, topic: str, facts: list[str], quiz: list[dict]) -> dict:
    if not output["lyrics"]:
        return {"coverage": 0.0}
    return {"coverage": loop.fact_coverage(output["lyrics"], {"topic": topic, "facts": facts, "quiz": quiz})["fact_coverage"]}


@weave.op
def naturalness(output: dict) -> dict:
    """Fixed judge: does this read like real, singable English rather than compressed shorthand?"""
    if not output["lyrics"]:
        return {"natural": 0.0}
    verdict = loop._chat_json(JUDGE,
        "You judge song lyrics for natural, singable English. Penalize abbreviations (like 'chem'), dropped "
        "articles or verbs, telegraphic shorthand, and awkward word order. Do not judge factual accuracy.",
        f"Lyrics:\n{output['lyrics']}\n\nReturn JSON: {{\"score\": integer 1-5, \"worst_line\": str}}",
        temperature=0)
    return {"natural": round((int(verdict["score"]) - 1) / 4, 3), "worst_line": verdict.get("worst_line", "")}


@weave.op
def speed(output: dict) -> dict:
    return {"seconds": output["seconds"]}


def build_dataset() -> list[dict]:
    if DATASET_PATH.exists():
        return json.loads(DATASET_PATH.read_text())
    rows = []
    for url in URLS:
        facts = loop.extract_facts(loop.fetch_source(url))
        rows.append({"url": url, "topic": facts["topic"], "facts": facts["facts"], "quiz": facts["quiz"]})
    DATASET_PATH.write_text(json.dumps(rows, indent=2))
    return rows


def main():
    weave.init(loop.WEAVE_PROJECT)
    rows = build_dataset()
    dataset = weave.Dataset(name="yue2-lyric-topics", rows=rows)
    out = pipeline.HACK / "runs/bakeoff.json"
    summaries = json.loads(out.read_text()) if out.exists() else {}
    for name in sys.argv[1:] or CANDIDATES:
        evaluation = weave.Evaluation(
            name="lyric-writer-bakeoff", dataset=dataset,
            scorers=[syllable_fit, facts_taught, naturalness, speed], trials=2,
        )
        summaries[name] = asyncio.run(evaluation.evaluate(LyricWriter(model_name=name)))
        out.write_text(json.dumps(summaries, indent=2, default=str))
        print("finished", name, flush=True)
    print("BAKEOFF_DONE")


if __name__ == "__main__":
    main()

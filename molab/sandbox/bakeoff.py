"""Weave Evaluation: which open-weight model writes the best first drafts for the loop?

Every candidate sets the same paragraphs to the melody; fixed scorers judge the drafts on syllable fit,
faithfulness to the source and speed.
    python bakeoff.py [model ...]   # updates runs/bakeoff.json; one comparable evaluation per model in Weave
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import weave

import faithful
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
    "google/gemma-4-31B-it",
]
DATASET_PATH = pipeline.HACK / "runs/bakeoff-paragraphs.json"


class LyricWriter(weave.Model):
    model_name: str

    @weave.op
    def predict(self, url: str, source: str, sections: list[dict]) -> dict:
        start = time.time()
        try:
            lyrics = loop.write_faithful(source, sections, model=self.model_name)
            return {"lyrics": lyrics, "seconds": round(time.time() - start, 1), "error": None}
        except Exception as error:
            return {"lyrics": None, "seconds": round(time.time() - start, 1), "error": f"{type(error).__name__}: {error}"[:300]}


@weave.op
def syllable_fit(output: dict, sections: list[dict]) -> dict:
    if not output["lyrics"]:
        return {"valid": False, "fit": 0.0}
    budget = [n for s in sections for n in s["phrases"]]
    result = pipeline.syllable_fit(output["lyrics"], budget, tolerance=loop.SYLLABLE_TOLERANCE)
    return {"valid": result["line_count_ok"], "fit": result["syllable_fit"]}


@weave.op
def faithful_to_text(output: dict, source: str) -> dict:
    if not output["lyrics"]:
        return {"faithfulness": 0.0}
    result = faithful.score(source, pipeline.lyric_lines(output["lyrics"]))
    return {"faithfulness": result["faithfulness"], "kept": result["kept"], "no_additions": result["no_additions"]}


@weave.op
def speed(output: dict) -> dict:
    return {"seconds": output["seconds"]}


def build_dataset() -> list[dict]:
    if DATASET_PATH.exists():
        return json.loads(DATASET_PATH.read_text())
    rows = []
    for url in URLS:
        source = loop.page_paragraphs(url)[0]
        rows.append({"url": url, "source": source, "sections": loop.song_plan(source)["sections"]})
    DATASET_PATH.write_text(json.dumps(rows, indent=2))
    return rows


def main():
    weave.init(loop.WEAVE_PROJECT)
    dataset = weave.Dataset(name="yue2-paragraphs", rows=build_dataset())
    out = pipeline.HACK / "runs/bakeoff.json"
    summaries = json.loads(out.read_text()) if out.exists() else {}
    for name in sys.argv[1:] or CANDIDATES:
        evaluation = weave.Evaluation(
            name="lyric-writer-bakeoff", dataset=dataset,
            scorers=[syllable_fit, faithful_to_text, speed], trials=2,
        )
        summaries[name] = asyncio.run(evaluation.evaluate(LyricWriter(model_name=name)))
        out.write_text(json.dumps(summaries, indent=2, default=str))
        print("finished", name, flush=True)
    print("BAKEOFF_DONE")


if __name__ == "__main__":
    main()

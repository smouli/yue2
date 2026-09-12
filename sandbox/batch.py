"""Run the loop over a list of pages and log the batch as a Weave evaluation.

    python batch.py baseline test-baseline 3 URL ...   # no playbook
    python batch.py learn    train          3 URL ...   # use the playbook and let the coach update it after each song
    python batch.py frozen   test-playbook  3 URL ...   # use the current playbook, no updates

Comparing `baseline` and `frozen` on the same held-out pages shows whether the learned playbook helps.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import weave

import loop
import pipeline
import playbook as pb


def metrics(history: list[dict]) -> dict:
    texts = [e for e in history if e["step"] == "text"]
    renders = [e for e in history if e["step"] == "render"]
    done = history[-1]
    first = texts[0]
    return {
        "first_draft_syllable_fit": first["syllable_fit"],
        "first_draft_facts": first["fact_coverage"],
        "first_draft_natural": first["natural"],
        "first_render_clarity": renders[0]["intelligibility"],
        "lyric_drafts": len(texts),
        "render_passes": len(renders),
        "final_clarity": done["best"]["intelligibility"],
        "final_facts": done["best"]["fact_coverage"],
        "final_natural": done["best"].get("natural"),
        "final_score": done["best"]["score"],
        "seconds": done.get("seconds"),
    }


def main():
    mode, prefix, takes, urls = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4:]
    assert mode in ("baseline", "learn", "frozen"), mode
    weave.init(loop.WEAVE_PROJECT)
    book = pb.load()
    evaluation = weave.EvaluationLogger(
        name=f"playbook-{prefix}", model=f"loop-{mode}", dataset=prefix,
        eval_attributes={"mode": mode, "takes": takes, "writer": loop.WRITER, "playbook_version_start": book["version"]},
    )
    summary_path = pipeline.HACK / f"runs/batch-{prefix}.json"
    rows = []
    for url in urls:
        slug = re.sub(r"[^a-z0-9]+", "-", url.rstrip("/").rsplit("/", 1)[-1].lower()).strip("-")[:30]
        run_name = f"{prefix}-{slug}"
        used = [] if mode == "baseline" else pb.rules(book)
        progress = pipeline.HACK / f"runs/{run_name}.progress.json"
        try:
            result = loop.run_loop(url, run_name, takes=takes, playbook=used, progress_path=str(progress))
        except Exception as error:  # one bad page should not sink the batch
            rows.append({"url": url, "run": run_name, "error": f"{type(error).__name__}: {error}"[:500]})
            summary_path.write_text(json.dumps(rows, indent=2))
            print("failed", run_name, error, flush=True)
            continue
        row = {"url": url, "run": run_name, "playbook_version": 0 if mode == "baseline" else book["version"],
               "rules_used": len(used), **metrics(result["history"])}
        if mode == "learn":
            book = pb.coach(book, pb.evidence(result["history"]))
            pb.save(book)
            row["playbook_version_after"] = book["version"]
            row["playbook_changes"] = book.get("changes", "")
        rows.append(row)
        summary_path.write_text(json.dumps(rows, indent=2))

        prediction = evaluation.log_prediction(inputs={"url": url}, output={"lyrics": result["best"]["lyrics"], "run": run_name})
        prediction.log_score("first_draft", {k: row[k] for k in row if k.startswith("first_")})
        prediction.log_score("effort", {"lyric_drafts": row["lyric_drafts"], "render_passes": row["render_passes"], "seconds": row["seconds"]})
        prediction.log_score("final", {k: row[k] for k in row if k.startswith("final_")})
        prediction.finish()
        print("finished", run_name, flush=True)
    evaluation.log_summary()
    print("BATCH_DONE", flush=True)


if __name__ == "__main__":
    main()

"""Run one loop in the background: python run_loop.py <url> <run_name> [takes]"""

import json
import sys

sys.path.insert(0, "/home/marimo/hack")

import weave

import loop

url, run_name = sys.argv[1], sys.argv[2]
takes = int(sys.argv[3]) if len(sys.argv) > 3 else 1
weave.init(loop.WEAVE_PROJECT)
progress = f"/home/marimo/hack/runs/{run_name}.progress.json"
result = loop.run_loop(url, run_name, takes=takes, progress_path=progress)
with open(f"/home/marimo/hack/runs/{run_name}.result.json", "w") as f:
    json.dump(result, f, indent=2)
print("LOOP_DONE")

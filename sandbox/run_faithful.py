"""Run faithful mode in the background: python run_faithful.py <text_file> <run_name> [takes] [url]"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import weave

import loop

text_file, run_name = sys.argv[1], sys.argv[2]
takes = int(sys.argv[3]) if len(sys.argv) > 3 else 1
url = sys.argv[4] if len(sys.argv) > 4 else ""
weave.init(loop.WEAVE_PROJECT)
runs_dir = Path.home() / ".yue2/runs"
runs_dir.mkdir(parents=True, exist_ok=True)
progress = str(runs_dir / f"{run_name}.progress.json")
result = loop.run_faithful(Path(text_file).read_text(), run_name, url=url, takes=takes, progress_path=progress)
with open(runs_dir / f"{run_name}.result.json", "w") as f:
    json.dump(result, f, indent=2)
print("LOOP_DONE")

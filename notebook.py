# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "openai==3.13.0",
#     "pronouncing==0.3.0",
#     "trafilatura==2.2.0",
#     "weave==0.53.9",
# ]
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell
def _():
    import json
    import subprocess
    from pathlib import Path

    import marimo as mo

    return Path, json, mo, subprocess


@app.cell
def smoke_test(Path, mo, subprocess):
    _run = Path("/home/marimo/hack/runs/smoke-city-lights")
    _mp3 = _run / "audio.mp3"
    if not _mp3.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(_run / "audio.flac"), "-b:a", "192k", str(_mp3)], check=True)

    mo.vstack([
        mo.md("## Smoke test: YuE2 example song\n59s of audio rendered in 30s on the RTX PRO 6000 (9 GB VRAM peak)"),
        mo.audio(src=_mp3.read_bytes()),
        mo.md("**Generated score (ABC)**"),
        mo.plain_text((_run / "score.abc").read_text()),
    ])
    return


@app.cell
def cover_test_v1(Path, json, mo, subprocess):
    _hack = Path("/home/marimo/hack")
    _orig = _hack / "runs/island-original-v1c1.mp3"
    _cover = _hack / "runs/cover-v1/audio.mp3"
    if not _orig.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "17.9", "-to", "59.8", "-i", str(_hack / "input/song.mp3"), "-b:a", "192k", str(_orig)], check=True)
    if not _cover.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(_hack / "runs/cover-v1/audio.flac"), "-b:a", "192k", str(_cover)], check=True)
    _req = json.loads((_hack / "edits/island_photosynthesis_v1.json").read_text())

    mo.vstack([
        mo.md("## Cover test v1: verse 1 + chorus 1, new lyrics on the original melody"),
        mo.hstack([
            mo.vstack([mo.md("**Original section**"), mo.audio(src=_orig.read_bytes())]),
            mo.vstack([mo.md("**YuE2 cover (photosynthesis lyrics)**"), mo.audio(src=_cover.read_bytes())]),
        ], widths="equal"),
        mo.md(f"**Style:** {_req['style']}"),
        mo.plain_text(_req["lyrics"]),
    ])
    return


@app.cell
def control_test(Path, json, mo, subprocess):
    _hack = Path("/home/marimo/hack")
    _control = json.loads((_hack / "runs/control_results.json").read_text())
    _v1_asr = json.loads((_hack / "runs/cover-v1/asr.json").read_text())
    _rows = [
        {"variant": "v1 (fitted)", "syllable_fit": 1.0, "melody_fidelity": 0.974, "intelligibility": _v1_asr["intelligibility"]},
    ] + [
        {"variant": _name, "syllable_fit": _r["syllable_fit"], "melody_fidelity": _r["melody_fidelity"], "intelligibility": _r["intelligibility"]}
        for _name, _r in _control.items()
    ]

    def _mp3(flac):
        _out = Path(flac).with_suffix(".mp3")
        if not _out.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(flac), "-b:a", "192k", str(_out)], check=True)
        return _out.read_bytes()

    mo.vstack([
        mo.md("## Control test: do the scorers catch badly fitted lyrics?"),
        mo.ui.table(_rows, selection=None),
        mo.hstack([
            mo.vstack([mo.md("**v1 (fitted)**"), mo.audio(src=_mp3(_hack / "runs/cover-v1/audio.flac"))]),
            mo.vstack([mo.md("**medium (9-10 syllables/line)**"), mo.audio(src=_mp3(_hack / "runs/control-medium/audio.flac"))]),
            mo.vstack([mo.md("**bad (17-27 syllables/line)**"), mo.audio(src=_mp3(_hack / "runs/control-bad/audio.flac"))]),
        ], widths="equal"),
    ])
    return


@app.cell
def run_picker_cell(Path, mo):
    _runs = sorted(p.name.removesuffix(".progress.json") for p in Path("/home/marimo/hack/runs").glob("*.progress.json"))
    run_picker = mo.ui.dropdown(options=_runs, value=_runs[-1] if _runs else None, label="Loop run")
    run_picker
    return (run_picker,)


@app.cell
def loop_run_viewer(Path, json, mo, run_picker, subprocess):
    _events = json.loads((Path("/home/marimo/hack/runs") / f"{run_picker.value}.progress.json").read_text())
    _facts = next(e for e in _events if e["step"] == "facts")
    _renders = [e for e in _events if e["step"] == "render"]
    _texts = [e for e in _events if e["step"] == "text"]

    def _mp3(flac):
        _out = Path(flac).with_suffix(".mp3")
        if not _out.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(flac), "-b:a", "192k", str(_out)], check=True)
        return _out.read_bytes()

    def _pass_card(e):
        _lines = "\n".join(f"{'✅' if l['score'] >= 0.85 else '⚠️'} {l['score']:.2f}  {l['line']}\n        heard: {l['heard']}" for l in e["lines"])
        return mo.vstack([
            mo.md(f"### Render pass {e['render_pass']}\n**intelligibility {e['intelligibility']:.2f}** · facts {e['fact_coverage']:.2f} · syllable fit {e['syllable_fit']:.2f} · melody {e['melody_fidelity']:.2f}"),
            mo.audio(src=_mp3(e["audio"])),
            mo.plain_text(_lines),
        ])

    mo.vstack([
        mo.md(f"## {_facts['topic']}: {len(_texts)} text passes, {len(_renders)} render passes"),
        mo.accordion({"Facts the song must teach": mo.md("\n".join(f"- {f}" for f in _facts["facts"]))}),
        mo.ui.table([{"pass": f"text {e['render_pass']}.{e['text_pass']}", "syllable_fit": e["syllable_fit"], "fact_coverage": e["fact_coverage"], "locked_lines": str(e.get("locked_lines", ""))} for e in _texts], selection=None, label="Text passes"),
        mo.hstack([_pass_card(e) for e in _renders], widths="equal", wrap=True),
    ])
    return


if __name__ == "__main__":
    app.run()

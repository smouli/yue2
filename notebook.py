# /// script
# requires-python = ">=3.13"
# dependencies = [
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


if __name__ == "__main__":
    app.run()

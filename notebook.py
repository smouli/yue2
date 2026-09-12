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


if __name__ == "__main__":
    app.run()

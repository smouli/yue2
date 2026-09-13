# /// script
# requires-python = ">=3.13"
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell
def _():
    import json
    import os
    import re
    import shlex
    import subprocess
    import sys
    import time
    from pathlib import Path

    import marimo as mo

    return Path, json, mo, os, re, shlex, subprocess, sys, time


@app.cell(hide_code=True)
def setup_paths(Path, mo):
    """Setup all paths for ~/.yue2/ local directory"""
    DEMO_CODE = str(Path(__file__).parent / "sandbox")
    DEMO_RUNS = Path.home() / ".yue2/runs"
    DEMO_RUNS.mkdir(parents=True, exist_ok=True)

    DEMO_LOGS = Path.home() / ".yue2/logs"
    DEMO_LOGS.mkdir(parents=True, exist_ok=True)

    return DEMO_CODE, DEMO_RUNS, DEMO_LOGS


@app.cell(hide_code=True)
def load_secrets(Path, os):
    """Load secrets from ~/.yue2/.secrets.env"""
    secrets_file = Path.home() / ".yue2/.secrets.env"

    if secrets_file.exists():
        for line in secrets_file.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ[k.strip()] = v.strip()

    return secrets_file.exists()


@app.cell(hide_code=True)
def demo_controls(Path, mo, sys, DEMO_CODE):
    """Demo controls - mode, URL, song selection"""
    if DEMO_CODE not in sys.path:
        sys.path.insert(0, DEMO_CODE)

    # Try to import local modules
    try:
        import singalong
        import faithful as demo_faithful
    except (ImportError, ModuleNotFoundError):
        class singalong:
            @staticmethod
            def from_result(*args, **kwargs):
                pass
        class demo_faithful:
            @staticmethod
            def clean_source(text):
                return text.strip()

    FAITHFUL = "Sing the text"
    SUMMARY = "Teach the key facts"

    get_demo_run, set_demo_run = mo.state(None)
    get_demo_done, set_demo_done = mo.state(None)

    demo_mode = mo.ui.radio(
        options=[FAITHFUL, SUMMARY],
        value=FAITHFUL,
        inline=True,
        label="Mode:"
    )

    demo_url = mo.ui.text(
        value="https://en.wikipedia.org/wiki/Industrial_Revolution",
        placeholder="Paste a Wikipedia or textbook URL",
        full_width=True,
        label="URL or text:"
    )

    demo_takes = mo.ui.slider(1, 4, value=3, show_value=True, label="Takes per render")

    demo_go = mo.ui.run_button(label="🎸 Make the song", kind="success")

    mo.vstack([
        mo.md("# 🎧 Listen to what you read"),
        mo.md("Paste a page. The agent sets its words to melody, sings them, listens with Whisper, and rewrites unclear parts."),
        demo_mode,
        demo_url,
    ])

    return (
        FAITHFUL,
        SUMMARY,
        demo_faithful,
        demo_go,
        demo_mode,
        demo_takes,
        demo_url,
        get_demo_done,
        get_demo_run,
        set_demo_done,
        set_demo_run,
        singalong,
    )


@app.cell(hide_code=True)
def demo_paragraphs(FAITHFUL, demo_faithful, demo_mode, demo_url, mo):
    """Select paragraph from page or paste custom"""
    @mo.cache
    def _page_paragraphs(url):
        try:
            import trafilatura
            _text = trafilatura.extract(trafilatura.fetch_url(url) or "") or ""
            return [demo_faithful.clean_source(_p) for _p in _text.splitlines() if 35 <= len(_p.split()) <= 110]
        except Exception:
            return []

    _paras = _page_paragraphs(demo_url.value) if demo_mode.value == FAITHFUL and demo_url.value.strip() else []
    _options = {f"{_i + 1}. {_p[:110]}{'…' if len(_p) > 110 else ''}": _p for _i, _p in enumerate(_paras[:30])}

    demo_paragraph = mo.ui.dropdown(
        options=_options,
        value=next(iter(_options), None),
        label="Paragraph to sing",
        full_width=True
    )

    demo_text = mo.ui.text_area(
        placeholder="…or paste your own paragraph (40–110 words sings best)",
        full_width=True,
        rows=3
    )

    return demo_paragraph, demo_text


@app.cell(hide_code=True)
def demo_launch(
    DEMO_CODE,
    DEMO_RUNS,
    DEMO_LOGS,
    FAITHFUL,
    Path,
    demo_go,
    demo_mode,
    demo_paragraph,
    demo_takes,
    demo_text,
    demo_url,
    mo,
    os,
    re,
    set_demo_done,
    set_demo_run,
    shlex,
    subprocess,
    sys,
    time,
):
    """Launch song generation in background"""
    if demo_go.value:
        _slug = re.sub(
            r"[^a-z0-9]+",
            "-",
            demo_url.value.rstrip("/").rsplit("/", 1)[-1].lower()
        ).strip("-")[:30] or "page"

        if demo_mode.value == FAITHFUL:
            _run = f"sing-{_slug}-{time.strftime('%H%M%S')}"
            _paragraph = demo_text.value.strip() or demo_paragraph.value or ""
            mo.stop(not _paragraph, mo.md("**Pick a paragraph or paste one first.**"))

            _file = DEMO_RUNS / f"{_run}.txt"
            _file.write_text(_paragraph)
            _cmd = f"run_faithful.py {_file} {_run} {demo_takes.value} {shlex.quote(demo_url.value)}"
        else:
            _run = f"facts-{_slug}-{time.strftime('%H%M%S')}"
            _cmd = f"run_loop.py {shlex.quote(demo_url.value)} {_run} {demo_takes.value}"

        _log_file = DEMO_LOGS / f"loop-{_run}.log"
        subprocess.Popen(
            f"cd {DEMO_CODE} && nohup {sys.executable} {_cmd} > {_log_file} 2>&1 &",
            shell=True
        )
        set_demo_done(None)
        set_demo_run(_run)

    return


@app.cell(hide_code=True)
def demo_progress(
    DEMO_RUNS,
    DEMO_LOGS,
    Path,
    get_demo_run,
    json,
    mo,
    set_demo_done,
    get_demo_done,
):
    """Show real-time progress of song generation"""
    _run = get_demo_run()
    mo.stop(_run is None, mo.md("_Press **Make the song** to start_"))

    _events_path = DEMO_RUNS / f"{_run}.progress.json"
    _log_path = DEMO_LOGS / f"loop-{_run}.log"
    _result_path = DEMO_RUNS / f"{_run}.result.json"

    _events = json.loads(_events_path.read_text()) if _events_path.exists() else []
    _log_text = _log_path.read_text() if _log_path.exists() else "⏳ Waiting for logs to appear..."
    _has_result = _result_path.exists()
    _failed = "Traceback" in _log_text or "Error" in _log_text
    _done = bool(_events) and _events[-1]["step"] == "done"

    if _done and get_demo_done() != _run:
        set_demo_done(_run)

    _facts = next((e for e in _events if e["step"] == "facts"), None)
    _texts = [e for e in _events if e["step"] == "text"]
    _renders = [e for e in _events if e["step"] == "render"]

    if _failed:
        _status = "❌ Process crashed"
    elif _done:
        _status = "✅ Done! Song generated"
    elif _has_result:
        _status = "📝 Finalizing..."
    elif _renders:
        _status = f"🎵 Rendering (pass {len(_renders)})"
    elif _texts:
        _status = f"✍️ Writing lyrics (draft {len(_texts)})"
    elif _facts:
        _status = f"📊 Processing facts"
    else:
        _status = f"📖 Starting up..."

    mo.vstack([
        mo.md(f"### Run: `{_run}`"),
        mo.md(f"**{_status}**"),
        mo.md(f"Events: {len(_events)} | Drafts: {len(_texts)} | Renders: {len(_renders)}"),
        mo.accordion({
            "📋 Live logs": mo.plain_text(_log_text[-2000:]),
        }),
    ])
    return


@app.cell(hide_code=True)
def debug_info(DEMO_RUNS, DEMO_LOGS, DEMO_CODE, Path, mo, subprocess):
    """Show debug info about what's running"""
    _run_files = sorted(DEMO_RUNS.glob("*.progress.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    _log_files = sorted(DEMO_LOGS.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)

    _info = f"""
    **System Info:**
    - Sandbox: `{DEMO_CODE}`
    - Runs dir: `{DEMO_RUNS}` ({len(list(DEMO_RUNS.glob('*')))} items)
    - Logs dir: `{DEMO_LOGS}` ({len(list(DEMO_LOGS.glob('*')))} items)

    **Recent runs:**
    """
    for f in _run_files[:3]:
        _mtime = f.stat().st_mtime
        _size = f.stat().st_size
        _info += f"\n- {f.name} ({_size} bytes)"

    mo.accordion({"🔧 Debug info": mo.md(_info)})
    return


@app.cell(hide_code=True)
def demo_player(DEMO_RUNS, Path, get_demo_done, json, mo, singalong, subprocess):
    """Play finished song"""
    _run = get_demo_done()
    mo.stop(_run is None)

    _events = json.loads((DEMO_RUNS / f"{_run}.progress.json").read_text())
    _facts = next(e for e in _events if e["step"] == "facts")
    _done = _events[-1]
    _flac = Path(_done["best"]["audio"])
    _mp3 = _flac.with_suffix(".mp3")

    if not _mp3.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(_flac), "-b:a", "160k", str(_mp3)],
            check=True
        )

    singalong.from_result(_done, _facts, _mp3)
    return


if __name__ == "__main__":
    app.run()

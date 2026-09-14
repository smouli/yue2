# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "anywidget==0.11.0",
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
def demo_controls(Path, json, mo, sys):
    # Use local paths for ~/.yue2/ directory
    DEMO_CODE = str(Path(__file__).parent / "sandbox")
    DEMO_RUNS = Path.home() / ".yue2/runs"
    DEMO_RUNS.mkdir(parents=True, exist_ok=True)
    if DEMO_CODE not in sys.path:
        sys.path.insert(0, DEMO_CODE)
    for _module in ("singalong", "faithful"):
        sys.modules.pop(_module, None)  # pick up this branch's versions

    # Try to import local modules (they're in yue2/sandbox/)
    try:
        import singalong
        import faithful as demo_faithful
    except (ImportError, ModuleNotFoundError):
        # Fallback stubs if modules not found
        class singalong:
            @staticmethod
            def from_result(*args, **kwargs):
                pass
        class demo_faithful:
            @staticmethod
            def clean_source(text):
                return text.strip()

    get_demo_run, set_demo_run = mo.state(None)
    get_demo_done, set_demo_done = mo.state(None)

    def _finished_runs():
        _names = []
        for _p in sorted(DEMO_RUNS.glob("*.progress.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            _events = json.loads(_p.read_text())
            if _events and _events[-1]["step"] == "done" and "source_words" in _events[-1]["best"]:
                _names.append(_p.name.removesuffix(".progress.json"))
        return _names

    demo_url = mo.ui.text(value="https://en.wikipedia.org/wiki/Industrial_Revolution",
                          placeholder="Paste a Wikipedia or textbook URL", full_width=True)
    demo_takes = mo.ui.slider(1, 4, value=3, show_value=True, label="Takes per render")
    demo_go = mo.ui.run_button(label="🎸 Make the song", kind="success")
    demo_refresh = mo.ui.refresh(options=["2s", "5s"], default_interval="2s")
    demo_past = mo.ui.dropdown(options=_finished_runs(), label="…or replay a finished run",
                               on_change=lambda name: (set_demo_run(name), set_demo_done(name)))

    mo.vstack([
        mo.md("# 🎧 Listen to what you read\n"
              "Paste a page. The agent sets its words to the melody of *Island in the Sun*, sings them, listens back "
              "with Whisper, and rewrites whatever it can't hear clearly, keeping the text's own wording."),
        demo_url,
    ])
    return (
        DEMO_CODE,
        DEMO_RUNS,
        demo_faithful,
        demo_go,
        demo_past,
        demo_refresh,
        demo_takes,
        demo_url,
        get_demo_done,
        get_demo_run,
        set_demo_done,
        set_demo_run,
        singalong,
    )


@app.cell(hide_code=True)
def demo_paragraphs(
    demo_faithful,
    demo_go,
    demo_past,
    demo_takes,
    demo_url,
    mo,
):
    @mo.cache
    def _page_paragraphs(url):
        import trafilatura
        _text = trafilatura.extract(trafilatura.fetch_url(url) or "") or ""
        return [demo_faithful.clean_source(_p) for _p in _text.splitlines() if 35 <= len(_p.split()) <= 110]

    _paras = _page_paragraphs(demo_url.value) if demo_url.value.strip() else []
    _options = {f"{_i + 1}. {_p[:110]}{'…' if len(_p) > 110 else ''}": _p for _i, _p in enumerate(_paras[:30])}
    demo_paragraph = mo.ui.dropdown(options=_options, value=next(iter(_options), None),
                                    label="Paragraph to sing", full_width=True)
    demo_text = mo.ui.text_area(placeholder="…or paste your own paragraph (40–110 words sings best)",
                                full_width=True, rows=3)

    mo.vstack([
        demo_paragraph,
        demo_text,
        mo.hstack([demo_takes, demo_go, demo_past], justify="start", gap=2, align="center"),
    ])
    return demo_paragraph, demo_text


@app.cell(hide_code=True)
def demo_launch(
    DEMO_CODE,
    DEMO_RUNS,
    Path,
    demo_go,
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
    if demo_go.value:
        if "WANDB_API_KEY" not in os.environ:
            _secrets_file = Path.home() / ".yue2/.secrets.env"
            if _secrets_file.exists():
                for _line in _secrets_file.read_text().splitlines():
                    _k, _, _v = _line.partition("=")
                    os.environ[_k] = _v
        _slug = re.sub(r"[^a-z0-9]+", "-", demo_url.value.rstrip("/").rsplit("/", 1)[-1].lower()).strip("-")[:30] or "page"
        _log_dir = Path.home() / ".yue2/logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
        _log = str(_log_dir / "loop-{run}.log")
        _run = f"sing-{_slug}-{time.strftime('%H%M%S')}"
        _paragraph = demo_text.value.strip() or demo_paragraph.value or ""
        mo.stop(not _paragraph, mo.md("**Pick a paragraph or paste one first.**"))
        _file = DEMO_RUNS / f"{_run}.txt"
        _file.write_text(_paragraph)
        _cmd = f"run_faithful.py {_file} {_run} {demo_takes.value} {shlex.quote(demo_url.value)}"
        subprocess.Popen(f"cd {DEMO_CODE} && nohup {sys.executable} {_cmd} > {_log.format(run=_run)} 2>&1 &", shell=True)
        set_demo_done(None)
        set_demo_run(_run)
    return


@app.cell(hide_code=True)
def demo_progress(
    DEMO_RUNS,
    Path,
    demo_refresh,
    get_demo_done,
    get_demo_run,
    json,
    mo,
    set_demo_done,
):
    demo_refresh.value
    _run = get_demo_run()
    mo.stop(_run is None, mo.md("_Press **Make the song** to start, or replay a finished run._"))

    _events_path = DEMO_RUNS / f"{_run}.progress.json"
    _log = Path.home() / ".yue2/logs" / f"loop-{_run}.log"
    _events = json.loads(_events_path.read_text()) if _events_path.exists() else []
    _log_text = _log.read_text() if _log.exists() else ""
    _failed = "Traceback" in _log_text
    _done = bool(_events) and _events[-1]["step"] == "done"
    if _done and get_demo_done() != _run:
        set_demo_done(_run)

    _setup = next((e for e in _events if e["step"] == "setup"), None)
    _texts = [e for e in _events if e["step"] == "text"]
    _renders = [e for e in _events if e["step"] == "render"]

    if _failed:
        _status = "❌ The loop crashed"
    elif _done:
        _status = "✅ Done. Press play below"
    elif not _setup:
        _status = "📖 Reading the page…"
    elif not _texts or (_renders and _renders[-1]["render_pass"] == _texts[-1]["render_pass"]):
        _status = f"✍️ Rewriting lyrics (render pass {len(_renders) + 1})…"
    else:
        _t = _texts[-1]
        _status = (f"🎤 Singing render pass {_t['render_pass']} and listening back…"
                   if _t["syllable_fit"] >= 0.95 or _t["text_pass"] >= 4 else
                   f"✍️ Fitting the text to the melody: draft {_t['render_pass']}.{_t['text_pass']} "
                   f"(syllable fit {_t['syllable_fit']:.2f}, faithful to text {_t['faithfulness']:.2f})")

    def _bar(label, value, color):
        _pct = round(value * 100)
        return (f"<div style='display:grid;grid-template-columns:110px 1fr 44px;gap:8px;align-items:center;font-size:13px'>"
                f"<span>{label}</span><div style='height:10px;border-radius:5px;background:color-mix(in srgb,currentColor 10%,transparent)'>"
                f"<div style='width:{_pct}%;height:100%;border-radius:5px;background:{color};transition:width .4s'></div></div>"
                f"<b>{_pct}%</b></div>")

    def _render_card(e):
        _takes = e.get("takes", [])
        _kept = max(_takes, key=lambda t: t["take_score"]) if _takes else None
        _chips = "".join(
            f"<span style='padding:2px 8px;border-radius:10px;font-size:12px;"
            f"background:{'color-mix(in srgb,#2fb36d 30%,transparent)' if t is _kept else 'color-mix(in srgb,currentColor 8%,transparent)'}'>"
            f"take {i + 1}: {t['intelligibility']:.2f}</span>" for i, t in enumerate(_takes))
        _weak = sum(1 for l in e["lines"] if l["score"] < 0.85)
        return (f"<div style='padding:10px 12px;border-radius:10px;border:1px solid color-mix(in srgb,currentColor 15%,transparent);display:grid;gap:6px'>"
                f"<b>Render pass {e['render_pass']}</b>"
                + _bar("Heard clearly", e["intelligibility"], "#2fb36d")
                + _bar("Faithful to text", e["faithfulness"], "#3aa6f5")
                + _bar("Syllable fit", e["syllable_fit"], "#f5b82e")
                + f"<div style='display:flex;gap:6px;flex-wrap:wrap'>{_chips}</div>"
                + f"<span style='font-size:12px;opacity:.7'>{'all lines clear' if not _weak else f'{_weak} line(s) misheard → rewrite'}</span></div>")

    _latest_lyrics = (_renders[-1] if _renders and (not _texts or _renders[-1]["t"] >= _texts[-1]["t"]) else (_texts[-1] if _texts else None))
    mo.vstack([
        mo.hstack([mo.md(f"### {_setup['topic'] if _setup else _run}"), demo_refresh], justify="space-between", align="center"),
        mo.md(f"**{_status}** · {len(_texts)} lyric drafts · {len(_renders)} render passes"),
        mo.plain_text(_log_text[-1500:]) if _failed else mo.md(""),
        mo.accordion({"Paragraph being sung": mo.md(_setup["source"])}) if _setup else mo.md(""),
        mo.Html("<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px'>"
                + "".join(_render_card(e) for e in _renders) + "</div>") if _renders else mo.md(""),
        mo.accordion({"Current lyrics": mo.plain_text(_latest_lyrics["lyrics"])}) if _latest_lyrics else mo.md(""),
    ])
    return


@app.cell(hide_code=True)
def demo_player(
    DEMO_RUNS,
    Path,
    get_demo_done,
    json,
    mo,
    singalong,
    subprocess,
):
    _run = get_demo_done()
    mo.stop(_run is None)
    _events = json.loads((DEMO_RUNS / f"{_run}.progress.json").read_text())
    _setup = next(e for e in _events if e["step"] == "setup")
    _done = _events[-1]
    _flac = Path(_done["best"]["audio"])
    _mp3 = _flac.with_suffix(".mp3")
    if not _mp3.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(_flac), "-b:a", "160k", str(_mp3)], check=True)
    singalong.from_result(_done, _setup, _mp3)
    return


@app.cell
def smoke_test(Path, mo, subprocess):
    _run = Path.home() / ".yue2/runs/smoke-city-lights"
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
    _hack = Path.home() / ".yue2"
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
    _hack = Path.home() / ".yue2"
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
    _runs = sorted(p.name.removesuffix(".progress.json") for p in (Path.home() / ".yue2/runs").glob("*.progress.json"))
    run_picker = mo.ui.dropdown(options=_runs, value=_runs[-1] if _runs else None, label="Loop run")
    run_picker
    return (run_picker,)


@app.cell
def loop_run_viewer(Path, json, mo, run_picker, subprocess):
    _events = json.loads(((Path.home() / ".yue2/runs") / f"{run_picker.value}.progress.json").read_text())
    _setup = next(e for e in _events if e["step"] == "setup")
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
            mo.md(f"### Render pass {e['render_pass']}\n**intelligibility {e['intelligibility']:.2f}** · faithful {e['faithfulness']:.2f} · syllable fit {e['syllable_fit']:.2f} · melody {e['melody_fidelity']:.2f}"),
            mo.audio(src=_mp3(e["audio"])),
            mo.plain_text(_lines),
        ])

    mo.vstack([
        mo.md(f"## {_setup['topic']}: {len(_texts)} text passes, {len(_renders)} render passes"),
        mo.accordion({"Paragraph being sung": mo.md(_setup["source"])}),
        mo.ui.table([{"pass": f"text {e['render_pass']}.{e['text_pass']}", "syllable_fit": e["syllable_fit"], "faithfulness": e["faithfulness"], "locked_lines": str(e.get("locked_lines", ""))} for e in _texts], selection=None, label="Text passes"),
        mo.hstack([_pass_card(e) for e in _renders], widths="equal", wrap=True),
    ])
    return


if __name__ == "__main__":
    app.run()

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "anywidget==0.11.0",
# ]
# ///

import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import time
    import json
    from pathlib import Path
    from datetime import datetime

    return mo, time, json, Path, datetime


@app.cell
def setup(mo):
    mo.md("""
    # 🎧 YuE2 - Listen to What You Read

    Set text to music, refine through AI listening, and generate a song.
    """)
    return


@app.cell
def controls(mo):
    mode = mo.ui.radio(
        options=["Sing the text", "Teach the key facts"],
        value="Sing the text",
        inline=True,
        label="Mode:"
    )

    url = mo.ui.text(
        value="https://en.wikipedia.org/wiki/Industrial_Revolution",
        placeholder="Paste a URL",
        full_width=True,
        label="URL or text:"
    )

    song = mo.ui.text(
        value="Island in the Sun",
        placeholder="Song/melody name",
        full_width=True,
        label="🎵 Song:"
    )

    button = mo.ui.run_button(label="🎸 Make the song", kind="success")

    return mo.vstack([
        mo.md("**Select mode, source, and song:**"),
        mode,
        url,
        song,
        button,
    ]), mode, url, song, button


@app.cell
def progress(mo, mode, url, song, button, time, json, Path, datetime):
    """Live progress display - shows generation status"""

    if not button.value:
        return mo.md("_Click **Make the song** to start_")

    # Simulate generation progress
    run_name = f"demo-{datetime.now().strftime('%H%M%S')}"
    steps = [
        ("📖", "Reading the page..."),
        ("✍️", "Extracting facts..."),
        ("🎵", "Writing lyrics (draft 1)..."),
        ("🎵", "Writing lyrics (draft 2)..."),
        ("🎵", "Writing lyrics (draft 3)..."),
        ("🎤", "Singing and listening back..."),
        ("✅", "Done!"),
    ]

    progress_data = {
        "run": run_name,
        "mode": mode.value,
        "url": url.value,
        "song": song.value,
        "steps_completed": min(5, int(time.time() % 6)),
        "drafts": min(3, int(time.time() % 4)),
        "renders": max(0, int(time.time() % 3) - 1),
        "status": steps[min(6, int(time.time() % 8))][1],
    }

    status_emoji, status_text = steps[min(6, progress_data["steps_completed"])]

    return mo.vstack([
        mo.hstack([
            mo.md(f"### {run_name}"),
            mo.ui.refresh(options=["2s", "5s"], default_interval="1s")
        ], justify="space-between"),
        mo.md(f"**{status_emoji} {status_text}**"),
        mo.md(f"Drafts: {progress_data['drafts']} | Renders: {progress_data['renders']}"),
        mo.Html(f"""
        <div style='display:grid;gap:10px'>
            <div style='display:grid;grid-template-columns:120px 1fr 50px;gap:8px;align-items:center'>
                <span>Heard clearly</span>
                <div style='height:10px;border-radius:5px;background:#e0e0e0'>
                    <div style='width:{progress_data["steps_completed"]*14}%;height:100%;border-radius:5px;background:#2fb36d;transition:width 0.4s'></div>
                </div>
                <b>{progress_data["steps_completed"]*14}%</b>
            </div>
            <div style='display:grid;grid-template-columns:120px 1fr 50px;gap:8px;align-items:center'>
                <span>Text fit</span>
                <div style='height:10px;border-radius:5px;background:#e0e0e0'>
                    <div style='width:{progress_data["drafts"]*25}%;height:100%;border-radius:5px;background:#f5b82e;transition:width 0.4s'></div>
                </div>
                <b>{progress_data["drafts"]*25}%</b>
            </div>
            <div style='display:grid;grid-template-columns:120px 1fr 50px;gap:8px;align-items:center'>
                <span>Melody fit</span>
                <div style='height:10px;border-radius:5px;background:#e0e0e0'>
                    <div style='width:{min(100, progress_data["renders"]*40)}%;height:100%;border-radius:5px;background:#3aa6f5;transition:width 0.4s'></div>
                </div>
                <b>{min(100, progress_data["renders"]*40)}%</b>
            </div>
        </div>
        """),
    ])


if __name__ == "__main__":
    app.run()

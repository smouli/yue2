"""Sing-along player: plays the song and highlights the lyric line and the source sentence it teaches."""

import base64
from pathlib import Path

import anywidget
import traitlets

_ESM = r"""
function render({ model, el }) {
  const controller = new AbortController();
  const { signal } = controller;

  el.innerHTML = `
    <div class="sa">
      <div class="sa-head">
        <div class="sa-topic"></div>
        <a class="sa-url" target="_blank" rel="noopener"></a>
      </div>
      <audio class="sa-audio" controls preload="auto"></audio>
      <div class="sa-cols">
        <section>
          <h4>🎵 Song</h4>
          <ol class="sa-lines"></ol>
        </section>
        <section>
          <h4>📖 What you're reading</h4>
          <div class="sa-source"></div>
        </section>
      </div>
    </div>`;

  const audio = el.querySelector(".sa-audio");
  const linesEl = el.querySelector(".sa-lines");
  const sourceEl = el.querySelector(".sa-source");

  function withTimes(lines, duration) {
    // Fill missing spans by spreading unknown lines evenly between known neighbours.
    const out = lines.map((l) => ({ ...l }));
    for (let i = 0; i < out.length; i++) {
      if (out[i].start != null) continue;
      const prevEnd = i > 0 && out[i - 1].end != null ? out[i - 1].end : 0;
      let j = i;
      while (j < out.length && out[j].start == null) j++;
      const nextStart = j < out.length ? out[j].start : duration || prevEnd + 4 * (j - i);
      const step = (nextStart - prevEnd) / (j - i);
      for (let k = i; k < j; k++) {
        out[k].start = prevEnd + step * (k - i);
        out[k].end = out[k].start + step;
      }
    }
    return out;
  }

  let timed = [];
  function build() {
    const lines = model.get("lines");
    timed = withTimes(lines, audio.duration);
    el.querySelector(".sa-topic").textContent = model.get("topic");
    const url = model.get("url");
    const a = el.querySelector(".sa-url");
    a.textContent = url;
    a.href = url;

    linesEl.replaceChildren(...timed.map((l, i) => {
      const li = document.createElement("li");
      li.dataset.i = i;
      li.innerHTML = `<span class="sa-text"></span><span class="sa-score"></span>`;
      li.querySelector(".sa-text").textContent = l.text;
      li.querySelector(".sa-score").textContent = l.score != null ? `heard ${Math.round(l.score * 100)}%` : "";
      li.addEventListener("click", () => { audio.currentTime = l.start; audio.play(); }, { signal });
      return li;
    }));

    // One paragraph per distinct source sentence, in song order.
    const seen = new Map();
    const paras = [];
    timed.forEach((l, i) => {
      const key = l.source || "";
      if (!key) return;
      if (!seen.has(key)) {
        const p = document.createElement("p");
        p.textContent = key;
        seen.set(key, p);
        paras.push(p);
      }
      seen.get(key).dataset["line" + i] = "1";
    });
    sourceEl.replaceChildren(...paras);
  }

  function highlight() {
    const t = audio.currentTime;
    const current = timed.findIndex((l, i) => t >= l.start && t < (timed[i + 1] ? timed[i + 1].start : Infinity));
    linesEl.querySelectorAll("li").forEach((li) => li.classList.toggle("on", Number(li.dataset.i) === current));
    sourceEl.querySelectorAll("p").forEach((p) => {
      const on = current >= 0 && p.dataset["line" + current] === "1";
      if (on && !p.classList.contains("on")) p.scrollIntoView({ block: "nearest", behavior: "smooth" });
      p.classList.toggle("on", on);
    });
  }

  audio.src = model.get("audio_src");
  audio.addEventListener("loadedmetadata", build, { signal });
  audio.addEventListener("timeupdate", highlight, { signal });
  model.on("change:lines", build);
  model.on("change:audio_src", () => { audio.src = model.get("audio_src"); });
  build();
  return () => controller.abort();
}
export default { render };
"""

_CSS = """
.sa { font: 14px/1.45 system-ui, sans-serif; display: grid; gap: 10px; min-height: 420px; }
.sa-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; }
.sa-topic { font-size: 20px; font-weight: 650; }
.sa-url { font-size: 12px; opacity: .65; overflow-wrap: anywhere; }
.sa-audio { width: 100%; }
.sa-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
.sa h4 { margin: 0 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; opacity: .7; }
.sa-lines { margin: 0; padding-left: 22px; display: grid; gap: 4px; }
.sa-lines li { padding: 6px 8px; border-radius: 8px; cursor: pointer; transition: background .2s, transform .2s; }
.sa-lines li:hover { background: color-mix(in srgb, currentColor 7%, transparent); }
.sa-lines li.on { background: color-mix(in srgb, #f5b82e 35%, transparent); font-weight: 600; transform: translateX(3px); }
.sa-score { margin-left: 8px; font-size: 11px; opacity: .55; font-weight: 400; }
.sa-source { max-height: 300px; overflow-y: auto; padding-right: 6px; }
.sa-source p { margin: 0 0 8px; padding: 6px 8px; border-radius: 8px; opacity: .6; transition: opacity .2s, background .2s; }
.sa-source p.on { opacity: 1; background: color-mix(in srgb, #3aa6f5 22%, transparent); }
"""


class SingAlong(anywidget.AnyWidget):
    _esm = _ESM
    _css = _CSS
    audio_src = traitlets.Unicode("").tag(sync=True)
    topic = traitlets.Unicode("").tag(sync=True)
    url = traitlets.Unicode("").tag(sync=True)
    lines = traitlets.List([]).tag(sync=True)


def from_result(done_event: dict, facts_event: dict, mp3_path: Path) -> SingAlong:
    """Build the player from a finished loop's progress events."""
    best = done_event["best"]
    by_line = {a["line"]: a["source_sentence"] for a in best.get("alignment", [])}
    lines = [{"text": l["line"], "start": l.get("start"), "end": l.get("end"), "score": l.get("score"),
              "source": by_line.get(l["line"], "")} for l in best.get("lines", [])]
    audio = "data:audio/mpeg;base64," + base64.b64encode(Path(mp3_path).read_bytes()).decode()
    return SingAlong(audio_src=audio, topic=facts_event["topic"], url=facts_event.get("url", ""), lines=lines)

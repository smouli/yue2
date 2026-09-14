const $ = (selector) => document.querySelector(selector);
const stage = $("#stage");
let pollTimer = null;
let shownSongId = null;
let playerSongId = null;

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((c) => c !== null && c !== undefined));
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

// ---------------------------------------------------------------------------------------------- compose

const source = $("#source");
function updateWordCount() {
  const words = source.value.trim().split(/\s+/).filter(Boolean).length;
  $("#word-count").textContent = `${words} words`;
}
source.addEventListener("input", updateWordCount);

$("#page-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const list = $("#paragraphs");
  const button = event.submitter;
  button.disabled = true;
  list.hidden = false;
  list.replaceChildren(el("p", { className: "muted small", textContent: "Fetching the page…" }));
  try {
    const { paragraphs } = await api(`/api/paragraphs?url=${encodeURIComponent($("#page-url").value)}`);
    if (!paragraphs.length) {
      list.replaceChildren(el("p", { className: "muted small", textContent: "No paragraphs of a singable length on that page." }));
      return;
    }
    list.replaceChildren(...paragraphs.map((text) => {
      const choice = el("button", { type: "button", textContent: text });
      choice.setAttribute("aria-pressed", "false");
      choice.addEventListener("click", () => {
        list.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
        choice.setAttribute("aria-pressed", "true");
        source.value = text;
        updateWordCount();
      });
      return choice;
    }));
  } catch (error) {
    list.replaceChildren(el("p", { className: "error", textContent: error.message }));
  } finally {
    button.disabled = false;
  }
});

$("#song-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#form-error");
  const button = $("#submit");
  error.hidden = true;
  button.disabled = true;
  try {
    const { id } = await api("/api/songs", {
      method: "POST",
      body: JSON.stringify({ source: source.value, url: $("#page-url").value, takes: Number($("#takes").value) }),
    });
    location.hash = `#/songs/${id}`;
    loadHistory();
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
});

// ---------------------------------------------------------------------------------------------- history

async function loadHistory() {
  const list = $("#history");
  try {
    const songs = await api("/api/songs");
    if (!songs.length) {
      list.replaceChildren(el("li", { className: "muted small", textContent: "No songs yet." }));
      return;
    }
    list.replaceChildren(...songs.map((song) => {
      const label = song.status === "done" && song.clarity != null ? `${Math.round(song.clarity * 100)}% clear` : song.status;
      const link = el("a", { href: `#/songs/${song.id}` },
        el("span", { className: "title", textContent: song.title || "Queued paragraph" }),
        el("span", { className: `badge ${song.status}`, textContent: label }));
      if (song.id === shownSongId) link.classList.add("current");
      return el("li", {}, link);
    }));
  } catch {
    list.replaceChildren(el("li", { className: "error", textContent: "Couldn't load songs." }));
  }
}

// ---------------------------------------------------------------------------------------------- song view

function bar(label, value, color) {
  const pct = Math.round((value ?? 0) * 100);
  return el("div", { className: "bar" },
    el("span", { textContent: label }),
    el("div", { className: "track" }, el("div", { className: "fill", style: `width:${pct}%;background:${color}` })),
    el("b", { textContent: `${pct}%` }));
}

function statusLine(song, texts, renders, setup) {
  if (song.status === "queued") return song.queue_ahead ? `⏳ Waiting in line (${song.queue_ahead} ahead)` : "⏳ Waiting for a worker";
  if (song.status === "failed") return "❌ The loop couldn't finish this song";
  if (song.status === "done") return "✅ Done. Press play below";
  if (!setup) return "🎼 Planning the song…";
  const lastText = texts.at(-1);
  const lastRender = renders.at(-1);
  if (lastText && (!lastRender || lastText.render_pass > lastRender.render_pass)) {
    const sung = lastText.syllable_fit >= 0.9 && lastText.faithfulness >= 0.85;
    return sung ? `🎤 Singing pass ${lastText.render_pass} and listening back…`
      : `✍️ Fitting the text to the melody (draft ${lastText.render_pass}.${lastText.text_pass})`;
  }
  return `✍️ Rewriting unclear lines (pass ${(lastRender?.render_pass ?? 0) + 1})…`;
}

function renderCard(event) {
  const kept = event.takes?.reduce((a, b) => (b.take_score > a.take_score ? b : a), event.takes[0]);
  const weak = event.lines.filter((l) => l.score < 0.85).length;
  return el("div", { className: "card" },
    el("h3", { textContent: `Pass ${event.render_pass}` }),
    bar("Heard clearly", event.intelligibility, "var(--green)"),
    bar("Faithful to text", event.faithfulness, "var(--blue)"),
    bar("Syllable fit", event.syllable_fit, "var(--accent)"),
    el("div", { className: "chips" }, ...(event.takes || []).map((t, i) =>
      el("span", { className: `chip${t === kept ? " kept" : ""}`, textContent: `take ${i + 1}: ${Math.round(t.intelligibility * 100)}%` }))),
    el("span", { className: "muted small", textContent: weak ? `${weak} line(s) misheard → rewrite` : "all lines clear" }));
}

function player(done, setup) {
  const best = done.best;
  const audio = el("audio", { controls: true, preload: "auto", src: best.audio_url });
  const lines = el("ol", { className: "lines" });
  const words = el("p", { className: "words" });
  const timed = best.lines.map((l, i) => ({ ...l, span: best.source_spans?.[i] ?? null }));
  timed.forEach((l, i) => {
    if (l.start == null) l.start = i > 0 ? timed[i - 1].end ?? 0 : 0;
  });

  lines.replaceChildren(...timed.map((line) => {
    const item = el("li", {}, line.line, el("span", { className: "heard", textContent: `heard ${Math.round(line.score * 100)}%` }));
    item.addEventListener("click", () => { audio.currentTime = line.start; audio.play(); });
    return item;
  }));
  words.replaceChildren(...(best.source_words || []).map((w) => el("span", { textContent: `${w} ` })));

  audio.addEventListener("timeupdate", () => {
    const t = audio.currentTime;
    const current = timed.findIndex((l, i) => t >= l.start && t < (timed[i + 1] ? timed[i + 1].start : Infinity));
    lines.querySelectorAll("li").forEach((item, i) => {
      const on = i === current;
      if (on && !item.classList.contains("on")) item.scrollIntoView({ block: "nearest", behavior: "smooth" });
      item.classList.toggle("on", on);
    });
    const span = current >= 0 ? timed[current].span : null;
    let first = null;
    words.querySelectorAll("span").forEach((w, i) => {
      const on = !!span && i >= span[0] && i <= span[1];
      if (on && !first) first = w;
      w.classList.toggle("on", on);
      w.classList.toggle("sung", !!span && i < span[0]);
    });
    first?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });

  return el("div", { className: "player" },
    el("h2", { textContent: "Sing-along" }),
    audio,
    el("div", { className: "karaoke" },
      el("div", {}, el("h4", { textContent: "Song" }), lines),
      el("div", {}, el("h4", { textContent: "What you're reading" }), words)));
}

async function showSong(id) {
  clearTimeout(pollTimer);
  shownSongId = id;
  let song;
  try {
    song = await api(`/api/songs/${id}`);
  } catch (error) {
    stage.replaceChildren(el("p", { className: "error", textContent: error.message }));
    return;
  }
  if (shownSongId !== id) return;
  const events = song.events || [];
  const setup = events.find((e) => e.step === "setup");
  const texts = events.filter((e) => e.step === "text");
  const renders = events.filter((e) => e.step === "render");
  const done = events.find((e) => e.step === "done");
  const latest = [...events].reverse().find((e) => e.lyrics);

  const keepPlayer = playerSongId === id && stage.querySelector(".player");
  const view = [
    el("h1", { textContent: setup?.topic || song.title || "Queued paragraph" }),
    el("div", { className: "status" },
      el("strong", { textContent: statusLine(song, texts, renders, setup) }),
      el("span", { className: "muted small", textContent: `${texts.length} lyric drafts · ${renders.length} render passes` })),
    song.status === "failed" ? el("pre", { className: "error", textContent: song.error || "Unknown error" }) : null,
    renders.length ? el("div", { className: "passes" }, ...renders.map(renderCard)) : null,
    keepPlayer ? stage.querySelector(".player") : done ? player(done, setup) : null,
    el("details", {}, el("summary", { textContent: "Paragraph being sung" }), el("p", { textContent: song.source })),
    latest ? el("details", {}, el("summary", { textContent: "Current lyrics" }), el("pre", { textContent: latest.lyrics })) : null,
  ];
  if (done) playerSongId = id;
  stage.replaceChildren(...view.filter(Boolean));

  if (song.status === "queued" || song.status === "running") {
    pollTimer = setTimeout(() => showSong(id), 2000);
  } else {
    loadHistory();
  }
}

function route() {
  const match = location.hash.match(/^#\/songs\/([\w-]+)/);
  if (match) {
    showSong(match[1]);
  } else {
    clearTimeout(pollTimer);
    shownSongId = null;
  }
  loadHistory();
}

window.addEventListener("hashchange", route);
route();

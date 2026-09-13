"""Render the demo video from real run data: captions, animated scores, and a synced karaoke segment.

    python demo_video.py   # writes /home/marimo/hack/video/yue2-demo.mp4

Frames are drawn with PIL and piped to ffmpeg; the audio is cut from the actual renders, and karaoke timing
comes from Whisper's word timestamps, so highlights follow the singing.
"""

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HACK = Path("/home/marimo/hack")
RUNS = HACK / "runs"
OUT = HACK / "video"
W, H, FPS = 1280, 720, 24
FACECAM = (1100, 20, 160)  # top-right bubble (x, y, diameter) kept clear in every scene except karaoke

BG = (14, 17, 23)
FG = (236, 238, 242)
MUTED = (140, 148, 160)
FAINT = (70, 76, 88)
YELLOW = (245, 184, 46)
BLUE = (58, 166, 245)
GREEN = (47, 179, 109)
RED = (232, 93, 88)

FONT_DIR = "/usr/share/fonts/opentype/inter"


def font(size, weight="Regular"):
    return ImageFont.truetype(f"{FONT_DIR}/Inter-{weight}.otf", size)


F_TITLE = font(56, "Bold")
F_H2 = font(34, "SemiBold")
F_BODY = font(26)
F_BODY_B = font(26, "SemiBold")
F_SMALL = font(20)
F_SMALL_B = font(20, "SemiBold")
F_LYRIC = font(28, "Medium")
F_PARA = font(24)


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def fade(t, start, end, edge=0.4):
    return ease((t - start) / edge) * ease((end - t) / edge)


def blend(color, alpha):
    return tuple(int(BG[i] + (color[i] - BG[i]) * alpha) for i in range(3))


def wrap(draw, text, fnt, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=fnt) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def centered(draw, y, text, fnt, color):
    draw.text(((W - draw.textlength(text, font=fnt)) / 2, y), text, font=fnt, fill=color)


# ------------------------------------------------------------------------------------------ data

industrial = json.loads((RUNS / "faithful-industrial-v2.progress.json").read_text())
renders = [e for e in industrial if e["step"] == "render"]
best = industrial[-1]["best"]
rescored = json.loads((RUNS / "diag/industrial-rescore.json").read_text())  # same take, number-aware scoring
calvin = json.loads((RUNS / "faithful-test-1.progress.json").read_text())
calvin_render = next(e for e in calvin if e["step"] == "render")
garbled = next(l for l in calvin_render["lines"] if l["line"].startswith("Such as ribulose"))
book = json.loads((HACK / "playbook.json").read_text())
GATE_PAGES = len(json.loads((RUNS / "gate-dataset.json").read_text()))
GATE_DRAFTS = GATE_PAGES * 5  # playbook.GATE_TRIALS
decisions = [d for step in book["decisions"] for d in step["decisions"] if d["action"] == "add"]

lines = best["lines"]
spans = best["source_spans"]
words = best["source_words"]
excerpt_a = (0.0, lines[4]["start"])                       # lines 1-4
excerpt_b = (lines[7]["start"] - 0.2, lines[9]["end"] + 0.6)  # steam power, iron production, occurred after

# ------------------------------------------------------------------------------------------ timeline

# The original recording is 115 BPM (SheetSage2 beat tracking); faithful songs are sung at 90 BPM for clarity.
# The video plays our song at the original tempo, pitch unchanged.
SPEED = 115 / 90
S_HOOK, S_ASK, S_PROBLEM, S_LOOP, S_ACTION = (0, 5), (5, 11.5), (11.5, 22.5), (22.5, 34.5), (34.5, 52.5)
KARAOKE_A = (53, 53 + (excerpt_a[1] - excerpt_a[0]) / SPEED)
KARAOKE_B = (KARAOKE_A[1] + 1.2, KARAOKE_A[1] + 1.2 + (excerpt_b[1] - excerpt_b[0]) / SPEED)
S_TUNE = (KARAOKE_B[1] + 0.8, KARAOKE_B[1] + 18)
S_LEARN = (S_TUNE[1], S_TUNE[1] + 12)
S_BUILT = (S_LEARN[1], S_LEARN[1] + 6)
DURATION = S_BUILT[1]
GARBLED_AT = S_PROBLEM[0] + 3.0
BED_VOLUME = 0.35
INSTRUMENTAL = HACK / "video/stems/htdemucs/audio/no_vocals.wav"  # our own render with the vocals removed


def scene_hook(d, t):
    a = fade(t, *S_HOOK)
    centered(d, 260, "We're building an app to make", F_TITLE, blend(FG, a))
    centered(d, 330, "and remix music", F_TITLE, blend(FG, a))


def scene_ask(d, t):
    a = fade(t, *S_ASK)
    centered(d, 220, "This weekend's question:", F_BODY, blend(MUTED, a))
    centered(d, 265, "can it sing what you're reading?", F_TITLE, blend(FG, a))
    b = a * ease((t - S_ASK[0] - 1.5) / 0.6)
    centered(d, 380, "Demo: a Wikipedia paragraph, sung to", F_BODY, blend(MUTED, b))
    centered(d, 418, "Island in the Sun by Weezer", F_BODY_B, blend(YELLOW, b))


def scene_problem(d, t):
    a = fade(t, *S_PROBLEM)
    centered(d, 120, "Singing real text is hard", F_H2, blend(FG, a))
    centered(d, 175, "First try on a biology paragraph, at full tempo:", F_BODY, blend(MUTED, a))
    b = a * ease((t - GARBLED_AT + 0.5) / 0.5)
    d.text((170, 280), "Lyric", font=F_SMALL_B, fill=blend(MUTED, b))
    d.text((170, 310), f"“{garbled['line']}”", font=F_LYRIC, fill=blend(FG, b))
    c = a * ease((t - GARBLED_AT - 2.5) / 0.5)
    d.text((170, 390), "What a listener heard", font=F_SMALL_B, fill=blend(MUTED, c))
    d.text((170, 420), f"“{garbled['heard']}”", font=F_LYRIC, fill=blend(RED, c))
    e = a * ease((t - GARBLED_AT - 4.5) / 0.5)
    centered(d, 530, f"Heard clearly: {round(calvin_render['intelligibility'] * 100)}% of the song", F_BODY_B, blend(RED, e))


def scene_loop(d, t):
    a = fade(t, *S_LOOP)
    centered(d, 70, "So it runs a loop", F_H2, blend(FG, a))
    steps = [
        ("Write", "fit the text to the melody, keeping its own words"),
        ("Sing", "three takes at once on a marimo molab GPU"),
        ("Listen", "Whisper checks every line"),
        ("Score", "clarity, faithfulness, syllable fit"),
        ("Rewrite", "only the lines it misheard"),
    ]
    box_w, gap, y = 212, 34, 230
    x0 = (W - (len(steps) * box_w + (len(steps) - 1) * gap)) / 2
    for i, (name, detail) in enumerate(steps):
        s = a * ease((t - S_LOOP[0] - 0.8 - i * 1.3) / 0.5)
        x = x0 + i * (box_w + gap)
        d.rounded_rectangle((x, y, x + box_w, y + 190), radius=16, outline=blend(YELLOW if i == 4 else BLUE, s), width=3)
        d.text((x + 18, y + 18), name, font=F_H2, fill=blend(FG, s))
        d.multiline_text((x + 18, y + 76), "\n".join(wrap(d, detail, F_SMALL, box_w - 36)), font=F_SMALL,
                         fill=blend(MUTED, s), spacing=6)
        if i < len(steps) - 1:
            ax = x + box_w + gap / 2
            d.polygon([(ax - 6, y + 88), (ax + 6, y + 95), (ax - 6, y + 102)], fill=blend(MUTED, s))
    s = a * ease((t - S_LOOP[0] - 7.5) / 0.6)
    left, right = x0 + box_w / 2, x0 + 4 * (box_w + gap) + box_w / 2
    d.line((right, y + 205, right, y + 250, left, y + 250, left, y + 205), fill=blend(YELLOW, s), width=3)
    d.polygon([(left - 8, y + 215), (left + 8, y + 215), (left, y + 202)], fill=blend(YELLOW, s))
    centered(d, y + 270, "until every line is heard clearly", F_BODY, blend(YELLOW, s))


def bar(d, x, y, w, label, value, color, alpha):
    d.text((x, y), label, font=F_SMALL, fill=blend(MUTED, alpha))
    d.rounded_rectangle((x, y + 30, x + w, y + 44), radius=7, fill=blend(FAINT, alpha * 0.6))
    d.rounded_rectangle((x, y + 30, x + max(14, w * value), y + 44), radius=7, fill=blend(color, alpha))
    d.text((x + w - 60, y), f"{round(value * 100)}%", font=F_SMALL_B, fill=blend(FG, alpha))


def scene_action(d, t):
    a = fade(t, *S_ACTION)
    centered(d, 90, "Industrial Revolution paragraph, pass by pass", F_H2, blend(FG, a))
    card_w, gap = 360, 30
    x0 = (W - (3 * card_w + 2 * gap)) / 2
    for i, e in enumerate(renders):
        s = a * ease((t - S_ACTION[0] - 0.6 - i * 1.6) / 0.6)
        grow = ease((t - S_ACTION[0] - 1.0 - i * 1.6) / 1.2)
        x, y = x0 + i * (card_w + gap), 195
        clarity = rescored["intelligibility"] if i == len(renders) - 1 else e["intelligibility"]
        d.rounded_rectangle((x, y, x + card_w, y + 250), radius=16, outline=blend(FAINT, s), width=2)
        d.text((x + 22, y + 18), f"Pass {e['render_pass']}", font=F_BODY_B, fill=blend(FG, s))
        bar(d, x + 22, y + 66, card_w - 44, "Heard clearly", clarity * grow, GREEN, s)
        bar(d, x + 22, y + 126, card_w - 44, "Faithful to the text", e["faithfulness"] * grow, BLUE, s)
        takes = "   ".join(f"{round(k['intelligibility'] * 100)}" for k in e["takes"])
        d.text((x + 22, y + 196), f"3 takes:  {takes}", font=F_SMALL, fill=blend(MUTED, s))
    s = a * ease((t - S_ACTION[0] - 7.5) / 0.6)
    first, last = renders[0]["lines"][0], rescored["lines"][0]
    d.text((150, 480), "Line 1, pass 1", font=F_SMALL_B, fill=blend(MUTED, s))
    d.text((150, 506), f"heard “{first['heard']}”", font=F_BODY, fill=blend(RED, s))
    d.text((1000, 506), f"{round(first['score'] * 100)}%", font=F_BODY_B, fill=blend(RED, s))
    s2 = a * ease((t - S_ACTION[0] - 10) / 0.6)
    d.text((150, 556), "Line 1, pass 3", font=F_SMALL_B, fill=blend(MUTED, s2))
    d.text((150, 582), f"heard “{last['heard']}”", font=F_BODY, fill=blend(GREEN, s2))
    d.text((1000, 582), f"{round(last['score'] * 100)}%", font=F_BODY_B, fill=blend(GREEN, s2))
    s3 = a * ease((t - S_ACTION[0] - 12.5) / 0.6)
    centered(d, 650, "Clear lines get locked. Misheard ones get rewritten and sung again.", F_BODY, blend(YELLOW, s3))


PARA_BOX = (660, 150, 1200, 640)


def _layout_paragraph():
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    x0, y0, x1, _ = PARA_BOX
    placed, x, y = [], x0, y0
    for word in words:
        width = probe.textlength(word + " ", font=F_PARA)
        if x + width > x1:
            x, y = x0, y + 40
        placed.append((x, y, width))
        x += width
    return placed


PARA_LAYOUT = _layout_paragraph()


def _current_line(song_t):
    for i, line in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else 1e9
        if line["start"] is not None and line["start"] <= song_t < nxt:
            return i
    return -1


def scene_karaoke(d, t):
    if KARAOKE_A[0] <= t < KARAOKE_A[1]:
        window, excerpt = KARAOKE_A, excerpt_a
    elif KARAOKE_B[0] <= t < KARAOKE_B[1]:
        window, excerpt = KARAOKE_B, excerpt_b
    else:
        a = fade(t, KARAOKE_A[1], KARAOKE_B[0], 0.3)
        centered(d, 340, "…", F_TITLE, blend(MUTED, a))
        return
    a = fade(t, *window, 0.35)
    song_t = excerpt[0] + (t - window[0]) * SPEED
    current = _current_line(song_t)
    d.text((80, 40), "It sings the paragraph itself.", font=F_H2, fill=blend(FG, a))
    d.text((80, 88), "Words light up as they're sung.", font=F_BODY, fill=blend(MUTED, a))
    d.text((80, 150), "SONG", font=F_SMALL_B, fill=blend(MUTED, a))
    d.text((PARA_BOX[0], 118), "WHAT YOU'RE READING  (Wikipedia, Industrial Revolution)", font=F_SMALL_B, fill=blend(MUTED, a))

    first = max(0, min(current - 2, len(lines) - 9)) if current >= 0 else 0
    for row, i in enumerate(range(first, min(len(lines), first + 9))):
        y = 190 + row * 50
        on = i == current
        if on:
            d.rounded_rectangle((70, y - 6, 600, y + 40), radius=10, fill=blend(YELLOW, a * 0.25))
        color = FG if on else (MUTED if i < current else FAINT)
        d.text((86, y), lines[i]["line"], font=F_LYRIC, fill=blend(color, a))

    span = spans[current] if 0 <= current < len(spans) else None
    for k, (x, y, width) in enumerate(PARA_LAYOUT):
        on = span is not None and span[0] <= k <= span[1]
        sung = span is not None and k < span[0]
        if on:
            d.rounded_rectangle((x - 4, y - 4, x + width - 2, y + 34), radius=6, fill=blend(BLUE, a * 0.45))
        color = FG if on else (MUTED if sung else FAINT)
        d.text((x, y), words[k], font=F_PARA, fill=blend(color, a))


TUNING = [
    ("Faithful vs. singable", "Keep the source's words; only drop filler, split sentences, spell out numbers",
     "Fitting the melody cost faithfulness 0.91 → 0.85"),
    ("Recognizable tempo vs. clarity", "Slow dense text from 115 to 90 BPM",
     "Clarity 0.17 → 0.52 on the same lyrics"),
    ("Speed vs. reliability", "Sing 3 takes per pass and keep the clearest",
     "One set of lyrics scored 0.22 to 0.81 across takes"),
    ("Fixing one line vs. breaking others", "Lock every line that was heard clearly",
     "Stopped rewrites from undoing earlier fixes"),
    ("More rules vs. better rules", "A rule is kept only if it wins an A/B test",
     "Untested rules lowered syllable fit 0.96 → 0.93"),
]


def scene_tune(d, t):
    a = fade(t, *S_TUNE)
    centered(d, 60, "What we tune", F_H2, blend(FG, a))
    centered(d, 108, "Every choice trades something. The loop measures both sides.", F_BODY, blend(MUTED, a))
    for r, (tradeoff, decision, evidence) in enumerate(TUNING):
        s = a * ease((t - S_TUNE[0] - 1.2 - r * 2.2) / 0.6)
        y = 196 + r * 100
        d.rounded_rectangle((70, y, 1210, y + 86), radius=12, outline=blend(FAINT, s), width=2)
        d.text((92, y + 14), tradeoff, font=F_BODY_B, fill=blend(YELLOW, s))
        d.text((92, y + 50), decision, font=F_SMALL, fill=blend(FG, s))
        ev_w = d.textlength(evidence, font=F_SMALL_B)
        d.text((1188 - ev_w, y + 16), evidence, font=F_SMALL_B, fill=blend(GREEN, s))


def scene_learn(d, t):
    a = fade(t, *S_LEARN)
    kept = [x for x in decisions if x["accepted"]]
    rejected = sorted([x for x in decisions if not x["accepted"]], key=lambda x: x["gain"])[:3]
    centered(d, 40, "Across songs, it learns rules and tests each one", F_H2, blend(FG, a))
    centered(d, 90, f"{len(book['learned_from'])} training songs proposed {len(decisions)} rules. Each was A/B tested on "
             f"{GATE_DRAFTS} drafts across {GATE_PAGES} new pages.", F_SMALL, blend(MUTED, a))
    centered(d, 120, f"{len(kept)} kept. No model weights were changed: the loop learns rules, not parameters.",
             F_SMALL, blend(MUTED, a))
    rows = [(x, True) for x in kept] + [(x, False) for x in rejected]
    for r, (x, ok) in enumerate(rows):
        s = a * ease((t - S_LEARN[0] - 1.0 - r * 0.9) / 0.5)
        y = 196 + r * 78
        badge = "KEPT" if ok else "REJECTED"
        color = GREEN if ok else RED
        d.rounded_rectangle((90, y, 230, y + 40), radius=8, outline=blend(color, s), width=2)
        d.text((160 - d.textlength(badge, font=F_SMALL_B) / 2, y + 8), badge, font=F_SMALL_B, fill=blend(color, s))
        gain = f"{x['gain']:+.3f}"
        d.text((255, y + 7), gain, font=F_BODY_B, fill=blend(color, s))
        text = wrap(d, x["rule"], F_SMALL, 820)[:2]
        d.multiline_text((370, y + 2 if len(text) > 1 else y + 9), "\n".join(text), font=F_SMALL, fill=blend(FG, s), spacing=4)


def scene_built(d, t):
    a = fade(t, *S_BUILT)
    centered(d, 250, "Built in a weekend", F_H2, blend(FG, a))
    centered(d, 320, "Weave traces and evaluations  ·  W&B Inference", F_BODY, blend(MUTED, a))
    centered(d, 360, "YuE2, SheetSage2 and Whisper on a marimo molab GPU", F_BODY, blend(MUTED, a))
    centered(d, 400, "Lyric writer picked by a Weave eval of 10 open models", F_BODY, blend(MUTED, a))


SCENES = [(S_HOOK, scene_hook), (S_ASK, scene_ask), (S_PROBLEM, scene_problem), (S_LOOP, scene_loop),
          (S_ACTION, scene_action), ((KARAOKE_A[0], KARAOKE_B[1]), scene_karaoke), (S_TUNE, scene_tune),
          (S_LEARN, scene_learn), (S_BUILT, scene_built)]


def render_video():
    OUT.mkdir(exist_ok=True)
    silent = OUT / "frames.mp4"
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(silent)],
        stdin=subprocess.PIPE)
    for n in range(int(DURATION * FPS)):
        t = n / FPS
        frame = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(frame)
        for (start, end), scene in SCENES:
            if start - 0.01 <= t < end:
                scene(draw, t)
        ffmpeg.stdin.write(frame.tobytes())
    ffmpeg.stdin.close()
    ffmpeg.wait()

    garbled_audio = Path(calvin_render["audio"])
    song = Path(best["audio"])
    clips = [
        (garbled_audio, garbled["start"], garbled["end"], GARBLED_AT),
        (song, *excerpt_a, KARAOKE_A[0]),
        (song, *excerpt_b, KARAOKE_B[0]),
    ]
    inputs, filters = [], []
    for k, (path, start, end, at) in enumerate(clips):
        inputs += ["-i", str(path)]
        ms = int(at * 1000)
        speed = SPEED if path == song else 1.0  # the garbled clip was already sung at 115 BPM
        length = (end - start) / speed
        filters.append(f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo,atrim={start}:{end},asetpts=PTS-STARTPTS,"
                       f"atempo={speed},afade=t=in:d=0.25,afade=t=out:st={max(0, length - 0.5)}:d=0.5,"
                       f"adelay={ms}|{ms},apad=whole_dur={DURATION}[a{k}]")

    # Instrumental bed: quiet under captions, dipped under the garbled clip, silent while the full song plays.
    ramp = 0.8
    window = lambda start, end: f"clip((t-({start}-{ramp}))/{ramp},0,1)*clip(({end}+{ramp}-t)/{ramp},0,1)"
    garbled_end = GARBLED_AT + garbled["end"] - garbled["start"]
    gain = (f"{BED_VOLUME}*max(0,1-0.75*{window(GARBLED_AT, garbled_end)}"
            f"-{window(KARAOKE_A[0], KARAOKE_B[1])})*clip(({DURATION}-t)/2,0,1)*clip(t/1.5,0,1)")
    bed = len(clips)
    inputs += ["-i", str(INSTRUMENTAL), "-i", str(INSTRUMENTAL)]  # two copies back to back cover the video
    filters.append(f"[{bed}:a][{bed + 1}:a]concat=n=2:v=0:a=1,aresample=44100,aformat=channel_layouts=stereo,atempo={SPEED},"
                   f"atrim=0:{DURATION},asetpts=PTS-STARTPTS,volume=eval=frame:volume='{gain}'[bed]")
    filters.append("".join(f"[a{k}]" for k in range(len(clips))) + f"[bed]amix=inputs={len(clips) + 1}:normalize=0:duration=longest[aout]")

    audio = OUT / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "[aout]", "-t", f"{DURATION:.2f}", str(audio)], check=True)
    audio_seconds = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                          str(audio)], capture_output=True, text=True, check=True).stdout)
    assert audio_seconds > DURATION - 1, f"audio track is {audio_seconds:.1f}s, expected {DURATION:.1f}s"

    timeline = {"duration": DURATION, "hook": S_HOOK, "ask": S_ASK, "problem": S_PROBLEM, "garbled_clip": [GARBLED_AT, garbled_end],
                "loop": S_LOOP, "action": S_ACTION, "karaoke": [KARAOKE_A[0], KARAOKE_B[1]], "tune": S_TUNE,
                "learn": S_LEARN, "built": S_BUILT, "facecam": FACECAM}
    (OUT / "timeline.json").write_text(json.dumps(timeline, indent=2))

    final = OUT / "yue2-demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{DURATION:.2f}", str(final)], check=True)
    return final


if __name__ == "__main__":
    print(render_video(), f"{DURATION:.1f}s")

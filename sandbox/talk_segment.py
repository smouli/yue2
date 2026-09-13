"""Render the 30-second "Under the hood" block (video only) in the demo video's style.

    python talk_segment.py OUT.mp4 [RUBRIC.png]

The presenter's face fills the circle on the left (added later by tools/add_facecam.py); the cards explain the
scoring rubric, the data the loop has produced, and the fine-tuning plan. Counts come from the run backup
(results/sandbox-results.tar.gz) at the time the sandbox shut down.
"""

import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

W, H, FPS, DURATION = 1280, 720, 24, 30.0
BG, FG, MUTED = (14, 17, 23), (236, 238, 242), (140, 148, 160)
YELLOW, BLUE = (245, 184, 46), (58, 166, 245)
FACECAM_LARGE = (90, 200, 320)

COUNTS = {"drafts": 225, "takes": 184, "passes": 68, "gate_drafts": 960}

# Faithful-mode rubric, with the targets from loop.run_faithful.
RUBRIC = [
    ("Score", "How it's measured", "Target", "Used for"),
    ("Heard clearly", "Whisper transcribes the song; each line compared letter by letter", "song 90%, every line 85%",
     "stop, lock lines, rewrite"),
    ("Faithful to the text", "Source words kept, in order; added words cost too", "85%", "stop rewriting"),
    ("Syllable fit", "Syllables (CMU dictionary) vs. notes in each melody line, ±1", "90%", "stop rewriting"),
    ("Melody check", "SheetSage2 re-transcribes the take; notes vs. the original", "guardrail", "report only"),
]
RUBRIC_FOOTER = ["Best take of 3 = average of song clarity and its worst line",
                 "Best pass = heard clearly × faithful to the text"]
RUBRIC_SECONDS = 10.0
CARDS = [
    ("Dataset so far", [f"{COUNTS['drafts']} lyric drafts, {COUNTS['takes']} sung takes, {COUNTS['passes']} render passes",
                        f"~{COUNTS['gate_drafts']} more drafts scored in rule A/B tests",
                        "Every draft, score and fix is traced in Weave"]),
    ("Next: fine-tuning", ["Train a small writer on the loop's best lyrics",
                           "Serve it as a LoRA on W&B Inference",
                           "Goal: first drafts that start close to finished"]),
]


def font(size, weight="Regular"):
    return ImageFont.truetype(f"/usr/share/fonts/opentype/inter/Inter-{weight}.otf", size)


F_H2, F_BODY_B, F_SMALL, F_SMALL_B, F_TINY = font(34, "SemiBold"), font(26, "SemiBold"), font(20), font(20, "SemiBold"), font(17)
GREEN = (47, 179, 109)


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def blend(color, alpha):
    return tuple(int(BG[i] + (color[i] - BG[i]) * alpha) for i in range(3))


def wrap(d, text, fnt, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if d.textlength(trial, font=fnt) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def draw_rubric(d, left, top, width, alpha):
    """The rubric as a table: score, how it's measured, target, what the loop uses it for."""
    columns = [0.22, 0.44, 0.17, 0.17]
    xs = [left]
    for share in columns[:-1]:
        xs.append(xs[-1] + width * share)
    line_h = F_TINY.size + 9
    pad = 12
    y = top
    for r, row in enumerate(RUBRIC):
        header = r == 0
        fonts = [F_SMALL_B if header or c == 0 else F_TINY for c in range(len(row))]
        cells = [wrap(d, cell, fonts[c], width * columns[c] - 18) for c, cell in enumerate(row)]
        height = 2 * pad + max(len(lines) for lines in cells) * max(line_h, fonts[0].size + 6)
        if not header:
            d.line((left, y, left + width, y), fill=blend((60, 66, 78), alpha), width=1)
        for c, lines in enumerate(cells):
            color = MUTED if header else (YELLOW if c == 0 else (GREEN if c == 2 else FG))
            step = max(line_h, fonts[c].size + 6)
            for k, text in enumerate(lines):
                d.text((xs[c] + 10, y + pad + k * step), text, font=fonts[c], fill=blend(color, alpha))
        y += height
    d.line((left, y, left + width, y), fill=blend((60, 66, 78), alpha), width=1)
    footer_h = F_SMALL.size + 12
    for k, text in enumerate(RUBRIC_FOOTER):
        d.text((left + 10, y + 16 + k * footer_h), "•  " + text, font=F_SMALL, fill=blend(MUTED, alpha))
    return y + 16 + len(RUBRIC_FOOTER) * footer_h


def frame(t):
    image = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(image)
    a = ease(t / 0.4) * ease((DURATION - t) / 0.4)
    x, y, size = FACECAM_LARGE
    d.ellipse((x - 6, y - 6, x + size + 6, y + size + 6), outline=blend(YELLOW, a), width=4)
    title = "Under the hood"
    d.text((x + size / 2 - d.textlength(title, font=F_H2) / 2, 110), title, font=F_H2, fill=blend(FG, a))

    rubric_alpha = a * ease((t - 0.6) / 0.6) * ease((RUBRIC_SECONDS - t) / 0.6)
    if rubric_alpha > 0:
        d.text((490, 70), "Scoring rubric (faithful mode)", font=F_BODY_B, fill=blend(FG, rubric_alpha))
        d.rounded_rectangle((480, 120, 1220, 640), radius=14, outline=blend(BLUE, rubric_alpha), width=2)
        draw_rubric(d, 490, 130, 720, rubric_alpha)

    for i, (heading, bullets) in enumerate(CARDS):
        s = a * ease((t - RUBRIC_SECONDS - 0.4 - i * 6) / 0.6)
        if s <= 0.01:
            continue  # drawing at zero opacity paints background color over whatever is underneath
        top = 120 + i * 250
        d.rounded_rectangle((490, top, 1210, top + 200), radius=14, outline=blend(YELLOW if i == 1 else BLUE, s), width=2)
        d.text((515, top + 18), heading, font=F_BODY_B, fill=blend(YELLOW if i == 1 else FG, s))
        for j, bullet in enumerate(bullets):
            d.text((515, top + 70 + j * 40), "•  " + bullet, font=F_SMALL, fill=blend(FG, s))
    return image


def rubric_image(out, width=1600, height=900):
    """Standalone rubric picture for slides and the submission page."""
    global F_SMALL, F_SMALL_B, F_TINY
    saved = (F_SMALL, F_SMALL_B, F_TINY)
    F_SMALL, F_SMALL_B, F_TINY = font(26), font(26, "SemiBold"), font(23)
    image = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(image)
    d.text((80, 60), "Scoring rubric", font=font(48, "Bold"), fill=FG)
    d.text((80, 128), "Faithful mode: sing the source paragraph itself, with minimal edits", font=font(26), fill=MUTED)
    draw_rubric(d, 80, 200, width - 160, 1.0)
    image.save(out)
    F_SMALL, F_SMALL_B, F_TINY = saved


def main(out):
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", out], stdin=subprocess.PIPE)
    for n in range(int(DURATION * FPS)):
        ffmpeg.stdin.write(frame(n / FPS).tobytes())
    ffmpeg.stdin.close()
    ffmpeg.wait()
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1])
    if len(sys.argv) > 2:
        rubric_image(sys.argv[2])

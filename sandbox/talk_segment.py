"""Render the 30-second "Under the hood" block (video only) in the demo video's style.

    python talk_segment.py OUT.mp4

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
CARDS = [
    ("Scoring rubric", ["Heard clearly: Whisper transcribes each line",
                        "Faithful to the text: source words kept, in order",
                        "Syllable fit: syllables matched to melody notes"]),
    ("Dataset so far", [f"{COUNTS['drafts']} lyric drafts, {COUNTS['takes']} sung takes, {COUNTS['passes']} render passes",
                        f"~{COUNTS['gate_drafts']} more drafts scored in rule A/B tests",
                        "Every draft, score and fix is traced in Weave"]),
    ("Next: fine-tuning", ["Train a small writer on the loop's best lyrics",
                           "Serve it as a LoRA on W&B Inference",
                           "Goal: first drafts that start close to finished"]),
]


def font(size, weight="Regular"):
    return ImageFont.truetype(f"/usr/share/fonts/opentype/inter/Inter-{weight}.otf", size)


F_H2, F_BODY_B, F_SMALL = font(34, "SemiBold"), font(26, "SemiBold"), font(20)


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def blend(color, alpha):
    return tuple(int(BG[i] + (color[i] - BG[i]) * alpha) for i in range(3))


def frame(t):
    image = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(image)
    a = ease(t / 0.4) * ease((DURATION - t) / 0.4)
    x, y, size = FACECAM_LARGE
    d.ellipse((x - 6, y - 6, x + size + 6, y + size + 6), outline=blend(YELLOW, a), width=4)
    title = "Under the hood"
    d.text((x + size / 2 - d.textlength(title, font=F_H2) / 2, 110), title, font=F_H2, fill=blend(FG, a))
    for i, (heading, bullets) in enumerate(CARDS):
        s = a * ease((t - 1.0 - i * 8) / 0.6)
        top = 70 + i * 205
        d.rounded_rectangle((490, top, 1210, top + 185), radius=14, outline=blend(YELLOW if i == 2 else BLUE, s), width=2)
        d.text((515, top + 16), heading, font=F_BODY_B, fill=blend(YELLOW if i == 2 else FG, s))
        for j, bullet in enumerate(bullets):
            d.text((515, top + 62 + j * 38), "•  " + bullet, font=F_SMALL, fill=blend(FG, s))
    return image


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

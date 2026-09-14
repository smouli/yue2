"""Assemble the final demo video from v3, the Under the hood block, and the facecam recording.

    python tools/final_cut.py results/yue2-demo-v3.mp4 results/parts/talk.mp4 results/facecam.mov \\
        --out results/yue2-demo-final.mp4

The recording was made against v3 (no Under the hood block), so its talk section sits after v3's ending.
This cut moves each part of the recording to where it belongs, using word timestamps from a Whisper
transcript of the recording (mlx-whisper, small.en):

    v3 intro to learning scene   <- recording 2.5s to 125.7s  (small bubble, hidden during karaoke)
    Under the hood block (36s)   <- "Here's how we score it" 142.96s to "finished" 177.45s  (large circle)
    closing credits (9.8s)       <- "everything runs on marimo molab GPUs" 177.9s to the end  (small bubble)
"""

import argparse
import subprocess

FPS = 24
V3_DURATION = 128.407
REC_OFFSET = 2.5                  # v3 started this many seconds into the recording

PART1_CUT = 121.9                 # last frame with the learning scene fully visible
PART1_HOLD = 1.3                  # lets "made the cut" finish before the block
PART1 = PART1_CUT + PART1_HOLD

TALK_REC = (142.16, 177.75)       # speech starts 142.96; 0.8s lead-in
TALK_FREEZES = [(9.0, 3.4), (16.0, 2.6)]  # (talk.mp4 time, seconds held): rubric stays up, cards follow the speech
TALK = 30.0 + sum(hold for _, hold in TALK_FREEZES)

BUILT_SRC = (122.4, V3_DURATION)  # closing credits in v3
BUILT_HOLD_AT, BUILT_HOLD = 126.0, 3.8
BUILT = (BUILT_SRC[1] - BUILT_SRC[0]) + BUILT_HOLD
CLOSE_REC = (177.3, 187.04)       # "everything" at 177.98

KARAOKE = (53.0, 92.407)
BED_SRC = (24.5, 33.5)            # music only, during v3's loop diagram
SMALL = (1100, 20, 160)
LARGE = (90, 200, 320)
DURATION = PART1 + TALK + BUILT


def circle(size: int, label: str) -> str:
    r = size // 2
    return (f"scale={size}:{size},format=yuva420p,geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':"
            f"a='if(lte(hypot(X-{r},Y-{r}),{r - 1}),255,0)'[{label}]")


def ring(size: int, label: str) -> str:
    outer = size // 2 + 3
    return (f"color=c=0xF5B82E:s={2 * outer}x{2 * outer}:r={FPS}:d={DURATION},format=yuva420p,"
            f"geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='if(lte(hypot(X-{outer},Y-{outer}),{outer}),255,0)'[{label}]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("v3")
    parser.add_argument("talk")
    parser.add_argument("facecam")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    f = []
    # --- picture: v3 part 1, the stretched talk block, the stretched credits
    f.append(f"[0:v]fps={FPS},trim=0:{PART1_CUT},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={PART1_HOLD}[p1]")
    cuts = [0.0] + [t for t, _ in TALK_FREEZES] + [30.0]
    holds = [hold for _, hold in TALK_FREEZES] + [0.0]
    f.append(f"[1:v]fps={FPS},split={len(cuts) - 1}" + "".join(f"[t{i}]" for i in range(len(cuts) - 1)))
    for i in range(len(cuts) - 1):
        pad = f",tpad=stop_mode=clone:stop_duration={holds[i]}" if holds[i] else ""
        f.append(f"[t{i}]trim={cuts[i]}:{cuts[i + 1]},setpts=PTS-STARTPTS{pad}[tp{i}]")
    f.append("".join(f"[tp{i}]" for i in range(len(cuts) - 1)) + f"concat=n={len(cuts) - 1}:v=1:a=0[p2]")
    f.append(f"[0:v]fps={FPS},split=2[b0][b1]")
    f.append(f"[b0]trim={BUILT_SRC[0]}:{BUILT_HOLD_AT},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={BUILT_HOLD}[p3a]")
    f.append(f"[b1]trim={BUILT_HOLD_AT}:{BUILT_SRC[1]},setpts=PTS-STARTPTS[p3b]")
    f.append("[p1][p2][p3a][p3b]concat=n=4:v=1:a=0[base]")

    # --- music: v3's own mix, with a quiet bed under the talk block and the held credits
    bed_len = BED_SRC[1] - BED_SRC[0]
    f.append("[0:a]aresample=48000,aformat=channel_layouts=stereo,asplit=5[m0][m1][m2][m3][m4]")
    f.append(f"[m0]atrim=0:{PART1},asetpts=PTS-STARTPTS[ma]")
    loops = int(TALK // bed_len) + 1
    f.append(f"[m1]atrim={BED_SRC[0]}:{BED_SRC[1]},asetpts=PTS-STARTPTS,aloop=loop={loops}:size={int(bed_len * 48000)},"
             f"atrim=0:{TALK},volume=0.6,afade=t=in:d=1,afade=t=out:st={TALK - 1}:d=1[mb]")
    f.append(f"[m2]atrim={BUILT_SRC[0]}:{BUILT_HOLD_AT},asetpts=PTS-STARTPTS[mc1]")
    f.append(f"[m3]atrim={BED_SRC[0]}:{BED_SRC[0] + BUILT_HOLD},asetpts=PTS-STARTPTS,volume=0.8[mc2]")
    f.append(f"[m4]atrim={BUILT_HOLD_AT}:{BUILT_SRC[1]},asetpts=PTS-STARTPTS[mc3]")
    f.append("[ma][mb][mc1][mc2][mc3]concat=n=5:v=0:a=1[music]")

    # --- facecam picture and voice, cut from the recording into the final timeline
    pieces = [(REC_OFFSET, REC_OFFSET + PART1), TALK_REC, CLOSE_REC]
    lengths = [PART1, TALK, BUILT]
    f.append(f"[2:v]fps={FPS},crop='min(iw,ih)':'min(iw,ih)',split=3" + "".join(f"[fv{i}]" for i in range(3)))
    f.append(f"[2:a]aresample=48000,aformat=channel_layouts=mono,asplit=3" + "".join(f"[fa{i}]" for i in range(3)))
    for i, ((start, end), length) in enumerate(zip(pieces, lengths)):
        used = min(end - start, length)
        f.append(f"[fv{i}]trim={start}:{start + used},setpts=PTS-STARTPTS,"
                 f"tpad=stop_mode=clone:stop_duration={max(0.0, length - used):.3f}[fvp{i}]")
        f.append(f"[fa{i}]atrim={start}:{start + used},asetpts=PTS-STARTPTS,apad=whole_dur={length}[fap{i}]")
    f.append("[fvp0][fvp1][fvp2]concat=n=3:v=1:a=0,split=2[fsmall][flarge]")
    f.append("[fap0][fap1][fap2]concat=n=3:v=0:a=1,highpass=f=80,loudnorm=I=-16:TP=-1.5,"
             "aformat=channel_layouts=stereo,asplit=2[voice][key]")
    f.append(f"[fsmall]{circle(SMALL[2], 'small')}")
    f.append(f"[flarge]{circle(LARGE[2], 'large')}")
    f.append(ring(SMALL[2], "smallring"))

    talk_start, talk_end = PART1, PART1 + TALK
    small_on = f"enable='not(between(t,{KARAOKE[0]},{KARAOKE[1]})+between(t,{talk_start},{talk_end}))'"
    large_on = f"enable='between(t,{talk_start},{talk_end})'"
    f.append(f"[base][smallring]overlay={SMALL[0] - 3}:{SMALL[1] - 3}:{small_on}[v1]")
    f.append(f"[v1][small]overlay={SMALL[0]}:{SMALL[1]}:{small_on}[v2]")
    f.append(f"[v2][large]overlay={LARGE[0]}:{LARGE[1]}:{large_on}[v]")

    f.append("[music][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[ducked]")
    f.append("[ducked][voice]amix=inputs=2:normalize=0:duration=first[a]")

    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", args.v3, "-i", args.talk, "-i", args.facecam,
                    "-filter_complex", ";".join(f), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{DURATION:.3f}", args.out], check=True)
    print(f"wrote {args.out} ({DURATION:.1f}s): talk block {talk_start:.1f}-{talk_end:.1f}s, credits from {talk_end:.1f}s")


if __name__ == "__main__":
    main()

"""Insert the "Under the hood" block into demo video v3 and write the matching timeline.

    python tools/splice_talk.py results/yue2-demo-v3.mp4 results/parts/talk.mp4 \\
        --out results/yue2-demo-v4.mp4 --timeline results/timeline.json

The block goes between the learning scene and the closing credits. Its music is a quiet loop of a
caption-only stretch of v3 (the loop diagram scene), so the voiceover sits on the same instrumental.
"""

import argparse
import json
import subprocess

# Scene timings of v3, from the renderer's timeline export before the sandbox shut down.
V3 = {
    "duration": 128.407, "hook": [0, 5], "ask": [5, 11.5], "problem": [11.5, 22.5], "garbled_clip": [14.5, 20.92],
    "loop": [22.5, 34.5], "action": [34.5, 52.5], "karaoke": [53.0, 92.407], "tune": [93.207, 110.407],
    "learn": [110.407, 122.407], "built": [122.407, 128.407],
    "facecam": [1100, 20, 160], "facecam_large": [90, 200, 320],
}
BED_SOURCE = (24.5, 33.5)  # music only, no clips, during the loop diagram
TALK_SECONDS = 30.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("v3")
    parser.add_argument("talk")
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeline", required=True)
    args = parser.parse_args()

    cut = V3["built"][0]
    bed_len = BED_SOURCE[1] - BED_SOURCE[0]
    repeats = int(TALK_SECONDS // bed_len) + 1
    filters = [
        f"[0:v]trim=0:{cut},setpts=PTS-STARTPTS[v1]",
        f"[0:a]atrim=0:{cut},asetpts=PTS-STARTPTS[a1]",
        f"[1:v]fps=24,setpts=PTS-STARTPTS[v2]",
        f"[0:a]atrim={BED_SOURCE[0]}:{BED_SOURCE[1]},asetpts=PTS-STARTPTS,asplit={repeats}"
        + "".join(f"[b{i}]" for i in range(repeats)),
        "".join(f"[b{i}]" for i in range(repeats))
        + f"concat=n={repeats}:v=0:a=1,atrim=0:{TALK_SECONDS},volume=0.6,afade=t=in:d=1,afade=t=out:st={TALK_SECONDS - 1}:d=1[a2]",
        f"[0:v]trim={cut}:{V3['duration']},setpts=PTS-STARTPTS[v3]",
        f"[0:a]atrim={cut}:{V3['duration']},asetpts=PTS-STARTPTS[a3]",
        "[v1][a1][v2][a2][v3][a3]concat=n=3:v=1:a=1[v][a]",
    ]
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", args.v3, "-i", args.talk,
                    "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", args.out],
                   check=True)

    timeline = dict(V3)
    timeline["talk"] = [cut, cut + TALK_SECONDS]
    timeline["built"] = [cut + TALK_SECONDS, V3["duration"] + TALK_SECONDS]
    timeline["duration"] = V3["duration"] + TALK_SECONDS
    open(args.timeline, "w").write(json.dumps(timeline, indent=2))
    print("wrote", args.out, "and", args.timeline)


if __name__ == "__main__":
    main()

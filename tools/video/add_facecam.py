"""Overlay a round facecam bubble and voiceover on the demo video.

    python tools/add_facecam.py results/yue2-demo.mp4 results/facecam.mov results/timeline.json \\
        --out results/yue2-demo-facecam.mp4 [--offset SECONDS]

The facecam recording should start with a clap at the moment the demo video starts playing; the clap is
found automatically (override with --offset, the time in the facecam file where the video starts).
The bubble is hidden during karaoke, and the video's music ducks under the voice.
"""

import argparse
import json
import re
import subprocess


def clap_offset(facecam: str, search_seconds: float = 15.0) -> float:
    """Time of the loudest short peak near the start of the recording."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-t", str(search_seconds), "-i", facecam, "-vn",
         "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.Peak_level", "-f", "null", "-"],
        capture_output=True, text=True)
    best_t, best_level, t = 0.0, -1e9, None
    for line in result.stderr.splitlines():
        if (m := re.search(r"pts_time:([\d.]+)", line)):
            t = float(m.group(1))
        elif (m := re.search(r"Peak_level=(-?[\d.]+|-inf)", line)) and t is not None:
            level = float(m.group(1)) if m.group(1) != "-inf" else -1e9
            if level > best_level:
                best_t, best_level = t, level
    return best_t


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("facecam")
    parser.add_argument("timeline")
    parser.add_argument("--out", required=True)
    parser.add_argument("--offset", type=float, help="seconds into the facecam file where the demo video starts")
    args = parser.parse_args()

    timeline = json.loads(open(args.timeline).read())
    x, y, size = timeline["facecam"]
    hide_start, hide_end = timeline["karaoke"]
    offset = args.offset if args.offset is not None else clap_offset(args.facecam)
    radius = size // 2
    print(f"facecam offset {offset:.2f}s; bubble hidden {hide_start:.1f}-{hide_end:.1f}s")

    bubble = (
        f"[1:v]trim=start={offset},setpts=PTS-STARTPTS,crop='min(iw,ih)':'min(iw,ih)',scale={size}:{size},"
        f"format=yuva420p,geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':"
        f"a='if(lte(hypot(X-{radius},Y-{radius}),{radius - 1}),255,0)'[face]"
    )
    outer = radius + 3
    visible = f"enable='not(between(t,{hide_start},{hide_end}))'"
    ring = (f"color=c=0xF5B82E:s={2 * outer}x{2 * outer}:d={timeline['duration']},format=yuva420p,"
            f"geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='if(lte(hypot(X-{outer},Y-{outer}),{outer}),255,0)'[ring]")
    overlay = (f"[0:v][ring]overlay={x - 3}:{y - 3}:{visible}[ringed];"
               f"[ringed][face]overlay={x}:{y}:{visible}:eof_action=pass[v]")
    voice = f"[1:a]atrim=start={offset},asetpts=PTS-STARTPTS,highpass=f=80,loudnorm=I=-16:TP=-1.5,asplit=2[voice][key]"
    duck = "[0:a][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[ducked]"
    mix = "[ducked][voice]amix=inputs=2:normalize=0:duration=first[a]"

    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", args.video, "-i", args.facecam,
         "-filter_complex", ";".join([bubble, ring, overlay, voice, duck, mix]),
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-t", str(timeline["duration"]), args.out],
        check=True)
    print("wrote", args.out)


if __name__ == "__main__":
    main()

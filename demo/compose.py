"""Compose docs/demo/demo.mp4: captions bar + mixed narration, one ffmpeg pass.

Reads demo/build/video/*.webm (raw, from record.py), demo/build/timings.json
(from synth.py) and demo/build/cues.json (from record.py). Writes
demo/build/captions.srt and docs/demo/demo.mp4.
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parent
BUILD = ROOT / "build"
OUT_DIR = PROJECT_ROOT / "docs" / "demo"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAD_WIDTH = 1440
PAD_HEIGHT = 1000  # viewport 1440x900 + a 100px caption bar underneath

# ClipForge's real image-generation stage runs well past the narration that
# describes it, leaving a long silent stretch between the last caption and
# the finished video actually appearing. Rather than make viewers sit
# through real backend latency with nothing being said, cut it down to a
# short beat. (start, end) in seconds, in the *recorded* timeline (before
# any cut is applied) - re-derive by eye per recording if cue timings shift.
DROP_RANGES: list[tuple[float, float]] = [(75.0, 93.0)]


def srt_timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(script: dict, timings: dict, cues: dict) -> str:
    lines = []
    idx = 1
    for scene in script["scenes"]:
        scene_id = scene["id"]
        cue = cues[scene_id]
        for phrase in timings[scene_id]["phrases"]:
            start = cue + phrase["start"]
            end = cue + phrase["end"] + 0.25
            lines.append(str(idx))
            lines.append(f"{srt_timestamp(start)} --> {srt_timestamp(end)}")
            lines.append(phrase["text"])
            lines.append("")
            idx += 1
    return "\n".join(lines)


def apply_drops(input_path: Path, duration: float, drop_ranges: list[tuple[float, float]],
                 out_path: Path) -> None:
    """Cuts drop_ranges out of input_path (video+audio together) via trim+concat."""
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in sorted(drop_ranges):
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        keep.append((cursor, duration))

    parts = []
    concat_inputs = []
    for i, (s, e) in enumerate(keep):
        vlabel, alabel = f"v{i}", f"a{i}"
        parts.append(f"[0:v]trim={s}:{e},setpts=PTS-STARTPTS[{vlabel}]")
        parts.append(f"[0:a]atrim={s}:{e},asetpts=PTS-STARTPTS[{alabel}]")
        concat_inputs.append(f"[{vlabel}][{alabel}]")
    parts.append(f"{''.join(concat_inputs)}concat=n={len(keep)}:v=1:a=1[v][a]")

    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-filter_complex", ";".join(parts),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def main():
    script = json.loads((ROOT / "script.json").read_text())
    timings = json.loads((BUILD / "timings.json").read_text())
    cues = json.loads((BUILD / "cues.json").read_text())

    srt_path = BUILD / "captions.srt"
    srt_path.write_text(build_srt(script, timings, cues))

    raw_video = next((BUILD / "video").glob("*.webm"))
    duration = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(raw_video)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )

    scene_ids = [s["id"] for s in script["scenes"]]
    mp3_paths = [BUILD / f"{sid}.mp3" for sid in scene_ids]

    inputs = ["-i", str(raw_video)]
    for mp3 in mp3_paths:
        inputs += ["-i", str(mp3)]

    audio_labels = []
    delay_filters = []
    for i, sid in enumerate(scene_ids, start=1):
        delay_ms = round(cues[sid] * 1000)
        label = f"a{i}"
        delay_filters.append(f"[{i}:a]adelay={delay_ms}:all=1[{label}]")
        audio_labels.append(f"[{label}]")

    video_filter = (
        f"[0:v]pad={PAD_WIDTH}:{PAD_HEIGHT}:0:0:color=0x0b0d11,"
        f"subtitles={srt_path.name}:force_style='FontName=DejaVu Sans,FontSize=10,Bold=1,"
        f"PrimaryColour=&HFFFFFF&,BorderStyle=1,Outline=0,Shadow=0,Alignment=2,MarginV=9'[v]"
    )
    mix_filter = (
        f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:normalize=0,"
        f"loudnorm=I=-16:TP=-1.5:LRA=9[a]"
    )
    filter_complex = ";".join([video_filter] + delay_filters + [mix_filter])

    composed_path = BUILD / "composed_full.mp4"
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(composed_path),
    ]
    # subtitles filter resolves its path relative to ffmpeg's cwd
    subprocess.run(cmd, cwd=BUILD, check=True)

    out_path = OUT_DIR / "demo.mp4"
    if DROP_RANGES:
        apply_drops(composed_path, duration, DROP_RANGES, out_path)
    else:
        out_path.write_bytes(composed_path.read_bytes())
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

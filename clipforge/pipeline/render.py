"""Timed captions + scene images + voiceover -> rendered vertical MP4 (ffmpeg).

Adapted from CloakMotion's vid-gen app/media/ffmpeg_media_processor.py
(create_zoomed_video, combine_videos, add_captions, merge_audio_to_video),
app/media/video_processor.py (caption font scaling/styling) and
app/editing_framework/video_editor.py (four-pass orchestration) - the same
raw-ffmpeg pipeline (zoom-pan clips -> concat -> drawtext captions -> audio
mux), minus the storage layer, particle overlay, background-music mixing,
thumbnail first-frame overlay and the DB-backed editor state.

Scene timing is computed here by evenly dividing the voiceover duration
across the CF-6 images instead of CloakMotion's 5-second getSegmentsWithTime
word-timestamp windows - CF-6 generates one image per script scene, so even
division keeps every image on screen for the same time.

The caption font is Titan One (bundled under clipforge/assets/fonts with its
SIL OFL 1.1 licence), matching CloakMotion's CaptionConfig default.
"""

import json
import random
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "TitanOne-Regular.ttf"

RENDER_WIDTH = 720
RENDER_HEIGHT = 1280
RENDER_FPS = 30

CAPTION_FONT_SIZE_RATIO = 0.08
CAPTION_SCALING_FACTOR = 0.35
CAPTION_FONT_COLOR = "#FFFFFF"
CAPTION_BORDER_COLOR = "#000000"
CAPTION_BORDER_WIDTH = 6
CAPTION_VERTICAL_OFFSET_PERCENT = 50.0
CAPTION_FADE_IN_SECONDS = 0.1

ZOOM_PRESCALE_WIDTH = 2160
ZOOM_IN_RATE = 0.002
ZOOM_OUT_RATE = 0.0025
ZOOM_OUT_START = 1.5

MAX_CLIP_WORKERS = 5

FFMPEG_BINARY = "ffmpeg"
FFPROBE_BINARY = "ffprobe"


def _run_ffmpeg(args: list[str], error_context: str) -> None:
    try:
        subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"{error_context}: {stderr}") from error


def probe_duration(media_path: Path) -> float:
    """Return the duration of an audio/video file in seconds via ffprobe."""
    command = [
        FFPROBE_BINARY,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as error:
        raise RuntimeError(f"Failed to probe duration of {media_path}: {error}") from error


def compute_scene_windows(duration: float, num_scenes: int) -> list[tuple[float, float]]:
    """Split the total duration into num_scenes equal (start, end) windows."""
    if duration <= 0:
        raise ValueError(f"Duration must be positive, got {duration}")
    if num_scenes <= 0:
        raise ValueError(f"num_scenes must be positive, got {num_scenes}")

    window = duration / num_scenes
    return [
        (
            round(i * window, 2),
            duration if i == num_scenes - 1 else round((i + 1) * window, 2),
        )
        for i in range(num_scenes)
    ]


def create_zoomed_clip(
    image_path: Path,
    duration: float,
    output_path: Path,
    width: int = RENDER_WIDTH,
    height: int = RENDER_HEIGHT,
    effect: str | None = None,
) -> Path:
    """Render one scene image into a duration-second clip with a Ken-Burns zoom."""
    frames = int(duration * RENDER_FPS)
    effects = {
        "in": (
            f"scale={ZOOM_PRESCALE_WIDTH}:-1,"
            f"zoompan=z='zoom+{ZOOM_IN_RATE}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={RENDER_FPS}"
        ),
        "out": (
            f"scale={ZOOM_PRESCALE_WIDTH}:-1,"
            f"zoompan=z='if(lte(zoom,1.0),{ZOOM_OUT_START},"
            f"max(1.001,zoom-{ZOOM_OUT_RATE}))':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={RENDER_FPS}"
        ),
    }
    chosen_effect = effects[effect or random.choice(["in", "out"])]

    command = [
        FFMPEG_BINARY,
        "-loop", "1",
        "-framerate", str(RENDER_FPS),
        "-i", str(image_path),
        "-vf", f"{chosen_effect},setsar=1/1,format=yuv420p",
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-y",
        str(output_path),
    ]
    _run_ffmpeg(command, f"Error creating zoomed clip from {image_path}")
    return output_path


def concat_clips(clip_paths: list[Path], output_path: Path) -> Path:
    """Concatenate scene clips into a single video via the concat demuxer."""
    if not clip_paths:
        raise ValueError("No clips to concatenate")

    with tempfile.TemporaryDirectory() as temp_dir:
        list_path = Path(temp_dir) / "clips.txt"
        list_path.write_text(
            "".join(f"file '{path}'\n" for path in clip_paths), encoding="utf-8"
        )

        command = [
            FFMPEG_BINARY,
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c:v", "libx264",
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-y",
            str(output_path),
        ]
        _run_ffmpeg(command, "Error combining clips")
    return output_path


def escape_drawtext(text: str) -> str:
    """Escape special characters for safe use in an ffmpeg drawtext filter."""
    special_chars = {
        "\\": "\\\\",  # Backslash
        "'": "''",  # Single quote (ffmpeg drawtext specific)
        '"': '\\"',  # Double quote
        "$": "\\$",  # Dollar sign
        "&": "\\&",  # Ampersand
        "|": "\\|",  # Pipe
        ";": "\\;",  # Command separator
        ">": "\\>",  # Redirect output
        "<": "\\<",  # Redirect input
        "*": "\\*",  # Wildcard
        "?": "\\?",  # Wildcard
        "(": "\\(",  # Parenthesis
        ")": "\\)",  # Parenthesis
        ":": "\\:",  # Colon (ffmpeg option separator)
        "=": "\\=",  # Equal sign
        ",": "\\,",  # Comma (ffmpeg filter separator)
        "%": "%%",  # Percent sign (format specifier)
        "[": "\\[",  # Square bracket (ffmpeg expressions)
        "]": "\\]",  # Square bracket (ffmpeg expressions)
    }
    return re.sub(
        r"([\\'\"$&|;><*?():=,%\[\]])",
        lambda match: special_chars[match.group(0)],
        text,
    )


def add_captions(
    video_path: Path,
    captions: list[tuple[tuple[float, float], str]],
    output_path: Path,
    font_path: Path = FONT_PATH,
    font_size: int | None = None,
    font_color: str = CAPTION_FONT_COLOR,
    border_color: str = CAPTION_BORDER_COLOR,
    border_width: int = CAPTION_BORDER_WIDTH,
    vertical_offset_percent: float = CAPTION_VERTICAL_OFFSET_PERCENT,
    fade_in_duration: float = CAPTION_FADE_IN_SECONDS,
    height: int = RENDER_HEIGHT,
) -> Path:
    """Burn timed captions into a video with a chain of drawtext filters."""
    if not captions:
        raise ValueError("No captions to burn in")
    if font_size is None:
        font_size = int(CAPTION_FONT_SIZE_RATIO * height * CAPTION_SCALING_FACTOR)
    vertical_offset_expr = f"h-text_h-(h*{vertical_offset_percent / 100})"

    filters = []
    for (start_time, end_time), text in captions:
        escaped_uppercase_text = escape_drawtext(text).upper()
        filters.append(
            f"drawtext=text='{escaped_uppercase_text}':"
            f"fontfile='{font_path}':"
            f"fontcolor={font_color}:fontsize={font_size}:"
            f"x=(w-text_w)/2:y={vertical_offset_expr}:"
            f"alpha='if(lt(t,{start_time}),0,"
            f"if(lt(t,{round(start_time + fade_in_duration, 2)}),"
            f"(t-{start_time})/{fade_in_duration},1))':"
            f"borderw={border_width}:bordercolor={border_color}:"
            f"enable='between(t,{start_time},{end_time})'"
        )

    command = [
        FFMPEG_BINARY,
        "-i", str(video_path),
        "-vf", ",".join(filters),
        "-c:v", "libx264",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-b:v", "2M",
        "-y",
        str(output_path),
    ]
    _run_ffmpeg(command, "Error adding captions")
    return output_path


def mux_audio(video_path: Path, audio_path: Path, output_path: Path) -> Path:
    """Combine a video with a voiceover audio track, trimming to the shorter stream."""
    command = [
        FFMPEG_BINARY,
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-y",
        str(output_path),
    ]
    _run_ffmpeg(command, "Error merging audio into video")
    return output_path


def load_captions(
    captions_path: Path,
) -> tuple[list[tuple[tuple[float, float], str]], float]:
    """Load the CF-5 captions JSON as timed captions plus the voiceover duration."""
    data = json.loads(Path(captions_path).read_text(encoding="utf-8"))
    timed_captions = [
        ((caption["start"], caption["end"]), caption["text"])
        for caption in data["timed_captions"]
    ]
    return timed_captions, float(data["duration"])


def render_video(
    images: list[Path],
    voiceover_path: Path,
    captions_path: Path,
    output_path: Path,
    width: int = RENDER_WIDTH,
    height: int = RENDER_HEIGHT,
) -> Path:
    """Render scene images, voiceover audio and timed captions into one vertical MP4."""
    if not images:
        raise ValueError("No scene images to render")
    if shutil.which(FFMPEG_BINARY) is None or shutil.which(FFPROBE_BINARY) is None:
        raise RuntimeError("ffmpeg and ffprobe must be installed and on PATH")
    if not FONT_PATH.exists():
        raise RuntimeError(f"Caption font not found: {FONT_PATH}")

    timed_captions, _ = load_captions(captions_path)
    duration = probe_duration(voiceover_path)
    windows = compute_scene_windows(duration, len(images))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        clip_paths = [temp_dir / f"clip_{index:02d}.mp4" for index in range(len(images))]

        with ThreadPoolExecutor(max_workers=min(MAX_CLIP_WORKERS, len(images))) as executor:
            list(
                executor.map(
                    partial(create_zoomed_clip, width=width, height=height),
                    images,
                    [end - start for start, end in windows],
                    clip_paths,
                )
            )

        concat_path = concat_clips(clip_paths, temp_dir / "concat.mp4")
        captioned_path = add_captions(
            concat_path, timed_captions, temp_dir / "captioned.mp4", height=height
        )
        mux_audio(captioned_path, voiceover_path, output_path)

    return output_path

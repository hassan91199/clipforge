"""CLI entrypoint: one text prompt in, a scheduled YouTube Short out.

Wires the pipeline stages CF-3 through CF-8 into a single command - the thing
that gets demoed. Stage timings are printed so the end-to-end runtime is
visible in the output (CF-10 clocks this exact number).
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from clipforge.config import load_config
from clipforge.pipeline.captions import generate_timed_captions
from clipforge.pipeline.images import auto_image_count, generate_image_prompts, generate_images
from clipforge.pipeline.render import render_video
from clipforge.pipeline.script_gen import generate_script
from clipforge.pipeline.tts import generate_voiceover
from clipforge.publish.youtube_publisher import publish_video

DEFAULT_NUM_IMAGES = 3  # seed value for manual-mode UI sliders only; auto mode ignores this
DEFAULT_PUBLISH_IN_HOURS = 24


def run_pipeline(
    config,
    prompt: str,
    output_dir: Path,
    num_images: int | None = None,
    video_duration: str = "30",
    publish_in_hours: int = DEFAULT_PUBLISH_IN_HOURS,
    upload: bool = True,
    publish_now: bool = False,
    youtube=None,
    on_event: Callable[[dict], None] | None = None,
) -> dict:
    """Run prompt -> script -> voiceover -> captions -> images -> render -> publish.

    `num_images=None` (the default) picks the scene count automatically from
    the generated script's sentence structure (see
    `clipforge.pipeline.images.auto_image_count`); pass an int to override it.

    Returns a summary dict with artifact paths and the publish response. When
    `on_event` is given, progress is reported as event dicts: stage_start,
    stage_done (with `seconds`), note, pipeline_done (with `total_seconds`).
    """
    pipeline_start = time.monotonic()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _emit(event: dict) -> None:
        if on_event is not None:
            on_event(event)

    def _stage(label: str, fn, *args, **kwargs):
        print(f"[{label}] started", flush=True)
        _emit({"event": "stage_start", "stage": label})
        start = time.monotonic()
        result = fn(*args, **kwargs)
        elapsed = time.monotonic() - start
        print(f"[{label}] done in {elapsed:.1f}s", flush=True)
        _emit({"event": "stage_done", "stage": label, "seconds": elapsed})
        return result

    script = _stage("script", generate_script, config, prompt, video_duration)
    (output_dir / "script.json").write_text(
        json.dumps(
            {"title": script.title, "caption": script.caption, "script": script.script},
            indent=2,
        )
    )
    print(f"  title: {script.title}", flush=True)
    _emit({"event": "note", "message": f"title: {script.title}"})

    voiceover_path = _stage(
        "voiceover", generate_voiceover, config, script.script, output_dir / "voiceover.mp3"
    )
    _stage(
        "captions", generate_timed_captions, config, voiceover_path, output_dir / "captions.json"
    )

    resolved_num_images = num_images
    if resolved_num_images is None:
        resolved_num_images = auto_image_count(script.script)
        print(f"[image-prompts] auto image count: {resolved_num_images}", flush=True)
        _emit({"event": "note", "message": f"auto image count: {resolved_num_images}"})

    prompts = _stage(
        "image-prompts",
        generate_image_prompts,
        config,
        script.script,
        resolved_num_images,
    )
    (output_dir / "prompts.json").write_text(json.dumps(prompts, indent=2))
    images_dir = output_dir / "images"
    image_paths = _stage("images", generate_images, config, prompts, images_dir)

    video_path = _stage(
        "render",
        render_video,
        image_paths,
        voiceover_path,
        output_dir / "captions.json",
        output_dir / "short.mp4",
    )

    publish_response = None
    watch_url = None
    if upload:
        publish_at = None
        if not publish_now:
            publish_at = datetime.now(timezone.utc) + timedelta(hours=publish_in_hours)
        publish_response = _stage(
            "publish",
            publish_video,
            config=config,
            video_path=video_path,
            title=script.title,
            description=script.caption,
            publish_at=publish_at,
            youtube=youtube,
        )
        video_id = publish_response["id"]
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        (output_dir / "publish.json").write_text(
            json.dumps(
                {"video_id": video_id, "watch_url": watch_url, "response": publish_response},
                indent=2,
            )
        )
        if publish_at:
            print(f"  scheduled: {publish_at.isoformat()}", flush=True)
            _emit({"event": "note", "message": f"scheduled: {publish_at.isoformat()}"})
        print(f"  {watch_url}", flush=True)
        _emit({"event": "note", "message": watch_url})

    total_seconds = time.monotonic() - pipeline_start
    print(f"[pipeline] total {total_seconds:.1f}s", flush=True)
    _emit({"event": "pipeline_done", "total_seconds": total_seconds})

    return {
        "run_dir": output_dir,
        "video_path": video_path,
        "title": script.title,
        "publish_response": publish_response,
        "watch_url": watch_url,
        "total_seconds": total_seconds,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipforge",
        description="One text prompt in, a scheduled YouTube Short out.",
    )
    parser.add_argument("prompt", help="What the video should be about")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for run artifacts (default: ./runs/run-<timestamp>/)",
    )
    parser.add_argument(
        "--num-images",
        type=int,
        default=None,
        help="Scene images per video (default: automatic, based on script length)",
    )
    parser.add_argument(
        "--duration",
        default="30",
        choices=["30", "30-60", "60-90"],
        help="Target video length for the generated script",
    )
    parser.add_argument(
        "--publish-in-hours",
        type=int,
        default=DEFAULT_PUBLISH_IN_HOURS,
        help="Schedule the video to publish this many hours from now",
    )
    parser.add_argument(
        "--publish-now", action="store_true", help="Publish immediately instead of scheduling"
    )
    parser.add_argument(
        "--no-upload", action="store_true", help="Render only, skip the YouTube upload"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = Path("runs") / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    try:
        run_pipeline(
            config,
            args.prompt,
            output_dir,
            num_images=args.num_images,
            video_duration=args.duration,
            publish_in_hours=args.publish_in_hours,
            upload=not args.no_upload,
            publish_now=args.publish_now,
        )
    except Exception as error:
        print(f"pipeline failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

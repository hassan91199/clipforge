"""Streamlit front-end: prompt in, live stage timings, video out.

Run with `streamlit run clipforge/ui.py` (see README). The app wraps
clipforge.cli.run_pipeline via its on_event callback, showing one timing row
per stage and the total elapsed time at the end - the same numbers the CLI
prints, so CF-10's measurement stays the single source of truth.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

# `streamlit run clipforge/ui.py` puts the script's dir on sys.path, not the
# repo root, so the clipforge package would not be importable without this.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from clipforge.cli import DEFAULT_NUM_IMAGES, DEFAULT_PUBLISH_IN_HOURS, run_pipeline
from clipforge.config import Config, load_config


class StageTracker:
    """Aggregates run_pipeline on_event dicts into display state.

    Pure logic with no Streamlit calls, so the event contract is unit-tested.
    """

    def __init__(self):
        self.stages: dict[str, dict] = {}
        self.notes: list[str] = []
        self.total_seconds: float | None = None

    def handle(self, event: dict) -> None:
        kind = event["event"]
        if kind == "stage_start":
            self.stages[event["stage"]] = {"status": "running", "seconds": None}
        elif kind == "stage_done":
            self.stages[event["stage"]] = {"status": "done", "seconds": event["seconds"]}
        elif kind == "note":
            self.notes.append(event["message"])
        elif kind == "pipeline_done":
            self.total_seconds = event["total_seconds"]

    @property
    def done(self) -> bool:
        return self.total_seconds is not None

    def done_stages(self) -> list[tuple[str, float]]:
        return [
            (stage, row["seconds"])
            for stage, row in self.stages.items()
            if row["status"] == "done"
        ]


def check_config() -> tuple[Config | None, str | None]:
    """Load config and report which keys are missing, without raising."""
    config = load_config()
    try:
        config.require(
            "openai_api_key",
            "replicate_api_token",
            "google_client_id",
            "google_client_secret",
        )
    except RuntimeError as error:
        return None, str(error)
    return config, None


def default_output_dir() -> Path:
    return Path("runs") / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def render_app() -> None:
    st.set_page_config(page_title="ClipForge", layout="centered")
    st.title("ClipForge")
    st.caption(
        "Text prompt in, a captioned vertical short out - rendered, and optionally "
        "uploaded and scheduled on YouTube."
    )

    config, config_error = check_config()
    if config_error:
        st.sidebar.error(config_error)

    with st.sidebar:
        st.header("Options")
        num_images = st.slider("Scene images", 1, 6, DEFAULT_NUM_IMAGES)
        video_duration = st.select_slider("Target length", options=["30", "30-60", "60-90"])
        upload = st.checkbox("Also schedule on YouTube", value=False)
        publish_now = False
        publish_in_hours = DEFAULT_PUBLISH_IN_HOURS
        if upload:
            publish_now = st.checkbox("Publish immediately", value=False)
            publish_in_hours = st.number_input(
                "Schedule hours ahead", min_value=1, max_value=168, value=DEFAULT_PUBLISH_IN_HOURS
            )

    prompt = st.text_area(
        "Video prompt", height=110, placeholder="Why the sky is blue, explained for curious kids"
    )

    generate_clicked = st.button(
        "Generate video", type="primary", disabled=not prompt.strip() or config_error is not None
    )
    if not generate_clicked:
        return

    tracker = StageTracker()
    output_dir = default_output_dir()
    stage_slots: dict[str, object] = {}
    status_box = st.empty()
    progress_bar = st.progress(0.0, text="starting...")
    stages_box = st.container()

    def handle_event(event: dict) -> None:
        tracker.handle(event)
        if event["event"] == "stage_start":
            with stages_box:
                stage_slots[event["stage"]] = st.status(event["stage"], state="running")
        elif event["event"] == "stage_done":
            stage_slots[event["stage"]].update(
                state="complete", label=f"{event['stage']} - {event['seconds']:.1f}s"
            )
            progress_bar.progress(
                min(len(tracker.done_stages()) / 7.0, 1.0),
                text=f"{event['stage']} done in {event['seconds']:.1f}s",
            )
        elif event["event"] == "note":
            with stages_box:
                st.caption(event["message"])

    try:
        summary = run_pipeline(
            config,
            prompt,
            output_dir,
            num_images=num_images,
            video_duration=video_duration,
            publish_in_hours=publish_in_hours,
            upload=upload,
            publish_now=publish_now,
            on_event=handle_event,
        )
    except Exception as error:
        status_box.error(f"pipeline failed: {error}")
        return

    progress_bar.progress(1.0, text="done")
    status_box.success(f"{summary['title']} - {summary['total_seconds']:.1f}s total")

    if summary["watch_url"]:
        st.markdown(f"Watch URL: {summary['watch_url']}")

    st.video(str(summary["video_path"]))

    with st.expander("Run artifacts"):
        st.write(f"`{output_dir}`")
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                st.write(f"- {path.relative_to(output_dir)}")

    st.subheader("Stage timings")
    for stage, seconds in tracker.done_stages():
        st.write(f"- {stage}: {seconds:.1f}s")
    st.write(f"**Total: {summary['total_seconds']:.1f}s**")


if __name__ == "__main__":
    render_app()

"""Streamlit front-end: prompt in, live stage timings, video out.

Run with `streamlit run clipforge/ui.py` (see README). The app wraps
clipforge.cli.run_pipeline via its on_event callback, showing one timing row
per stage and the total elapsed time at the end - the same numbers the CLI
prints, so CF-10's measurement stays the single source of truth.
"""

import sys
from datetime import datetime
from pathlib import Path

# `streamlit run clipforge/ui.py` puts the script's dir on sys.path, not the
# repo root, so the clipforge package would not be importable without this.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from clipforge.cli import DEFAULT_NUM_IMAGES, DEFAULT_PUBLISH_IN_HOURS, run_pipeline
from clipforge.config import Config, demo_config, load_config
from clipforge.quota import check_and_increment


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
            (stage, row["seconds"]) for stage, row in self.stages.items() if row["status"] == "done"
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


def client_ip() -> str | None:
    """Best-effort caller IP from the request headers Cloud Run's front end sets.

    X-Forwarded-For can carry a proxy chain; the first entry is the original
    client. No header (local `streamlit run`, no DEMO_BUCKET) means no
    per-IP check - the global cap still applies.
    """
    forwarded = st.context.headers.get("X-Forwarded-For")
    if not forwarded:
        return None
    return forwarded.split(",")[0].strip()


def operator_mode() -> bool:
    """True when provider keys come from the operator's env (.env).

    No env keys means the public demo: visitors bring their own keys via the
    sidebar form and YouTube publishing stays out of the demo path.
    """
    config = load_config()
    return bool(config.openai_api_key and config.replicate_api_token)


def demo_keys_config() -> Config | None:
    """BYO-keys sidebar form for the public demo.

    Keys live in st.session_state only - never written to disk or logs. The
    form submit triggers a rerun, so the stored config is returned on the
    next script run.
    """
    if "demo_keys" in st.session_state:
        return st.session_state["demo_keys"]
    with st.sidebar:
        st.caption(
            "Public demo - bring your own API keys. "
            "They stay in this browser session and are never stored."
        )
        with st.form("demo_keys_form"):
            openai_key = st.text_input("OpenAI API key", type="password")
            replicate_token = st.text_input("Replicate API token", type="password")
            submitted = st.form_submit_button("Use these keys")
    if submitted and openai_key.strip() and replicate_token.strip():
        st.session_state["demo_keys"] = demo_config(openai_key.strip(), replicate_token.strip())
    return st.session_state.get("demo_keys")


def render_app() -> None:
    st.set_page_config(page_title="ClipForge", layout="centered")
    st.title("ClipForge")
    st.caption(
        "Text prompt in, a captioned vertical short out - rendered, and optionally "
        "uploaded and scheduled on YouTube."
    )

    config: Config | None = None
    config_error: str | None = None
    upload_available = False
    if operator_mode():
        config, config_error = check_config()
        upload_available = config_error is None
        if config_error:
            st.sidebar.error(config_error)
    else:
        config = demo_keys_config()

    with st.sidebar:
        st.header("Options")
        num_images = st.slider("Scene images", 1, 6, DEFAULT_NUM_IMAGES)
        video_duration = st.select_slider("Target length", options=["30", "30-60", "60-90"])
        upload = False
        publish_now = False
        publish_in_hours = DEFAULT_PUBLISH_IN_HOURS
        if upload_available:
            upload = st.checkbox("Also schedule on YouTube", value=False)
            if upload:
                publish_now = st.checkbox("Publish immediately", value=False)
                publish_in_hours = st.number_input(
                    "Schedule hours ahead",
                    min_value=1,
                    max_value=168,
                    value=DEFAULT_PUBLISH_IN_HOURS,
                )
        else:
            st.caption("YouTube publishing is disabled in the public demo.")

    prompt = st.text_area(
        "Video prompt", height=110, placeholder="Why the sky is blue, explained for curious kids"
    )

    generate_clicked = st.button(
        "Generate video",
        type="primary",
        disabled=not prompt.strip() or config is None or config_error is not None,
    )
    if not generate_clicked:
        return

    allowed, used = check_and_increment(client_ip=client_ip())
    if not allowed:
        st.error(f"Daily demo limit reached ({used} runs today) - please try again tomorrow.")
        return

    tracker = StageTracker()
    output_dir = default_output_dir()
    stage_slots: dict[str, object] = {}
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
        st.error(f"pipeline failed: {error}")
        return

    progress_bar.progress(1.0, text="done")
    st.success(f"{summary['title']} - {summary['total_seconds']:.1f}s total")

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

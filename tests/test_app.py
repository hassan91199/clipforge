"""Browser-layer tests: drive clipforge/ui.py through Streamlit AppTest.

AppTest executes the real app script in-process, so widget interaction
(prompt typed, button clicked) and rendered output (success message, stage
timings, video element) are asserted without a browser. run_pipeline is
stubbed at clipforge.cli (the script re-imports it on every script run, so
the patch must target cli, not the exec'd ui namespace) with the same fake
event contract the real pipeline emits, costing zero API calls.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "clipforge" / "ui.py"

CONFIG_ENV = {
    "OPENAI_API_KEY": "test-openai",
    "REPLICATE_API_TOKEN": "test-replicate",
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
}

STAGES = ["script", "voiceover", "captions", "image-prompts", "images", "render"]


def _tiny_mp4(path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.2:size=128x128:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def _fake_run_pipeline(video_path: Path, fail_with: Exception | None = None):
    """Build a run_pipeline stub matching cli.run_pipeline's signature."""

    def fake(
        config,
        prompt,
        output_dir,
        num_images=3,
        video_duration="30",
        publish_in_hours=24,
        upload=False,
        publish_now=False,
        youtube=None,
        on_event=None,
    ):
        if fail_with is not None:
            raise fail_with
        assert on_event is not None
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(video_path, output_dir / "short.mp4")
        for stage in STAGES:
            on_event({"event": "stage_start", "stage": stage})
            on_event({"event": "stage_done", "stage": stage, "seconds": 1.5})
        on_event({"event": "note", "message": "title: Fake title"})
        if upload:
            on_event({"event": "stage_start", "stage": "publish"})
            on_event({"event": "stage_done", "stage": "publish", "seconds": 9.3})
            on_event({"event": "note", "message": "https://www.youtube.com/watch?v=vidXYZ"})
        on_event({"event": "pipeline_done", "total_seconds": 10.0})
        return {
            "title": "Fake title",
            "total_seconds": 10.0,
            "watch_url": "https://www.youtube.com/watch?v=vidXYZ" if upload else "",
            "video_path": video_path,
        }

    return fake


def _all_text(at) -> str:
    """Every user-visible string in the app render, for substring asserts."""
    chunks = [
        element.value
        for element in list(at.text)
        + list(at.markdown)
        + list(at.caption)
        + list(at.title)
        + list(at.success)
        + list(at.error)
    ]
    for expander in at.expander:
        chunks.append(expander.label)
    return "\n".join(chunks)


class AppTests(unittest.TestCase):
    """render_app driven through AppTest with a stubbed pipeline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.video = _tiny_mp4(Path(self.tmp.name) / "short.mp4")
        self.at = AppTest.from_file(APP_PATH, default_timeout=15)

    @contextmanager
    def _app(self, upload=False, config_present=True, side_effect=None):
        stub = _fake_run_pipeline(self.video, fail_with=side_effect)
        env = dict(CONFIG_ENV) if config_present else {key: "" for key in CONFIG_ENV}
        with patch.dict(os.environ, env), patch("clipforge.cli.run_pipeline", stub):
            self.at.run()
            yield self.at

    def _type_prompt_and_generate(self, upload=False):
        # set_value does not rerun the script; a browser user's textarea edit
        # commits on blur, so mirror that with an explicit run() before click.
        self.at.text_area[0].set_value("Why is the sky blue, for kids").run()
        if upload:
            self.at.checkbox[0].set_value(True).run()
        self.at.button[0].click().run()

    def test_prompt_and_generate_show_total_and_stage_timings(self):
        with self._app():
            self._type_prompt_and_generate()
            text = _all_text(self.at)
            self.assertIn("Fake title - 10.0s total", text)
            self.assertIn("**Total: 10.0s**", text)
            for stage in STAGES:
                self.assertIn(f"- {stage}: 1.5s", text)

    def test_video_element_rendered_after_success(self):
        with self._app() as at:
            self._type_prompt_and_generate()
            # AppTest has no typed video accessor; st.video lands as unknown
            # element in the tree, which is enough to assert it was embedded.
            self.assertEqual(len(list(at.get("video"))), 1)

    def test_success_without_upload_has_no_watch_url_markdown(self):
        with self._app():
            self._type_prompt_and_generate()
            self.assertNotIn("https://www.youtube.com/watch?v=vidXYZ", _all_text(self.at))

    def test_upload_checkbox_passes_upload_true_and_shows_watch_url(self):
        with self._app(upload=True) as at:
            self._type_prompt_and_generate(upload=True)
            self.assertIn("Watch URL: https://www.youtube.com/watch?v=vidXYZ", _all_text(at))

    def test_publish_controls_appear_only_when_upload_checked(self):
        with self._app() as at:
            self.assertEqual([box.label for box in at.number_input], [])
            at.checkbox[0].set_value(True).run()
            labels = [box.label for box in at.number_input]
            self.assertIn("Schedule hours ahead", labels)

    def test_generate_disabled_while_prompt_empty(self):
        with self._app() as at:
            self.assertTrue(at.button[0].disabled)

    def test_demo_mode_shows_keys_form_and_disables_generate(self):
        with self._app(config_present=False) as at:
            labels = [box.label for box in at.text_input]
            self.assertIn("OpenAI API key", labels)
            self.assertIn("Replicate API token", labels)
            generate = [b for b in at.button if b.label == "Generate video"][0]
            self.assertTrue(generate.disabled)

    def test_demo_keys_submit_enables_generate_without_upload(self):
        with self._app(config_present=False) as at:
            at.text_input[0].set_value("sk-demo").run()
            at.text_input[1].set_value("r8-demo").run()
            submit = [b for b in at.button if b.label == "Use these keys"][0]
            submit.click().run()
            at.text_area[0].set_value("Why is the sky blue, for kids").run()
            generate = [b for b in at.button if b.label == "Generate video"][0]
            self.assertFalse(generate.disabled)
            generate.click().run()
            self.assertIn("Fake title - 10.0s total", _all_text(at))
            # publishing is excluded from the public demo path
            self.assertNotIn("Also schedule on YouTube", [c.label for c in at.checkbox])

    def test_pipeline_failure_shows_error_message(self):
        with self._app(side_effect=RuntimeError("FLUX down")) as at:
            self._type_prompt_and_generate()
            self.assertIn("pipeline failed: FLUX down", at.error[0].value)

    def test_daily_cap_blocks_generate_in_demo_mode(self):
        with patch("clipforge.quota.check_and_increment", return_value=(False, 100)):
            with self._app(config_present=False) as at:
                at.text_input[0].set_value("sk-demo").run()
                at.text_input[1].set_value("r8-demo").run()
                submit = [b for b in at.button if b.label == "Use these keys"][0]
                submit.click().run()
                at.text_area[0].set_value("prompt").run()
                generate = [b for b in at.button if b.label == "Generate video"][0]
                generate.click().run()
        self.assertIn("Daily demo limit reached (100 runs today)", at.error[0].value)

    def test_run_artifacts_expander_lists_files(self):
        with self._app() as at:
            self._type_prompt_and_generate()
            expander = at.expander[0]
            expander.run()
            text = "\n".join(element.value for element in expander.markdown)
            self.assertIn("short.mp4", text)


if __name__ == "__main__":
    unittest.main()

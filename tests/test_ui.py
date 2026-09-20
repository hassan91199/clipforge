import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from clipforge.cli import run_pipeline
from clipforge.pipeline.script_gen import VideoScript
from clipforge.ui import StageTracker, check_config, default_output_dir


def _events(callback, stages):
    """Invoke callback with a realistic event sequence for the given stages."""
    for stage in stages:
        callback({"event": "stage_start", "stage": stage})
        callback({"event": "stage_done", "stage": stage, "seconds": 1.5})
    callback({"event": "note", "message": "title: Test title"})
    callback({"event": "pipeline_done", "total_seconds": 79.2})


class StageTrackerTests(unittest.TestCase):
    def test_events_populate_stage_rows_in_order(self):
        tracker = StageTracker()
        _events(tracker.handle, ["script", "voiceover"])
        self.assertEqual([stage for stage, _ in tracker.done_stages()], ["script", "voiceover"])
        self.assertEqual(tracker.done_stages()[0], ("script", 1.5))

    def test_notes_collected_and_total_set(self):
        tracker = StageTracker()
        _events(tracker.handle, ["script"])
        self.assertEqual(tracker.notes, ["title: Test title"])
        self.assertEqual(tracker.total_seconds, 79.2)
        self.assertTrue(tracker.done)

    def test_running_stage_not_yet_done(self):
        tracker = StageTracker()
        tracker.handle({"event": "stage_start", "stage": "render"})
        self.assertEqual(tracker.done_stages(), [])
        self.assertFalse(tracker.done)

    def test_pipeline_done_marks_done(self):
        tracker = StageTracker()
        tracker.handle({"event": "pipeline_done", "total_seconds": 10.0})
        self.assertTrue(tracker.done)
        self.assertEqual(tracker.total_seconds, 10.0)


class CheckConfigTests(unittest.TestCase):
    def test_missing_config_reported_not_raised(self):
        with patch("clipforge.ui.load_config") as load_config:
            load_config.return_value.require.side_effect = RuntimeError(
                "Missing required config: OPENAI_API_KEY (check .env)"
            )
            config, error = check_config()
        self.assertIsNone(config)
        self.assertIn("OPENAI_API_KEY", error)

    def test_valid_config_returned(self):
        with patch("clipforge.ui.load_config") as load_config:
            load_config.return_value.require.return_value = None
            config, error = check_config()
        self.assertIsNotNone(config)
        self.assertIsNone(error)


class DefaultOutputDirTests(unittest.TestCase):
    def test_under_runs_with_timestamp(self):
        run_dir = default_output_dir()
        self.assertEqual(run_dir.parent.name, "runs")
        self.assertTrue(run_dir.name.startswith("run-"))


class PipelineEventTests(unittest.TestCase):
    """The on_event contract run_pipeline exposes to the UI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name) / "run"

    def _run(self, callback, upload=True):
        with (
            patch("clipforge.cli.generate_script") as fake_script,
            patch("clipforge.cli.generate_voiceover") as fake_voiceover,
            patch("clipforge.cli.generate_timed_captions") as fake_captions,
            patch("clipforge.cli.generate_image_prompts") as fake_prompts,
            patch("clipforge.cli.generate_images") as fake_images,
            patch("clipforge.cli.render_video") as fake_render,
            patch("clipforge.cli.publish_video") as fake_publish,
        ):
            fake_script.return_value = VideoScript(title="T", caption="C", script="Narration.")
            fake_voiceover.side_effect = lambda config, text, path, **kw: (
                path.write_bytes(b"mp3"),
                path,
            )[1]
            fake_captions.side_effect = lambda config, audio, path, **kw: (
                path.write_text(json.dumps({"timed_captions": []})),
                path,
            )[1]
            fake_prompts.return_value = ["p1"]
            fake_images.side_effect = lambda config, prompts, out, **kw: []
            fake_render.side_effect = lambda *args, **kw: self.run_dir / "short.mp4"
            fake_publish.return_value = {"id": "vidXYZ"}
            run_pipeline(
                MagicMock(),
                "prompt",
                self.run_dir,
                upload=upload,
                youtube=MagicMock(),
                on_event=callback,
            )

    def test_events_fire_in_stage_order_with_durations(self):
        events = []
        self._run(events.append)
        started = [e["stage"] for e in events if e["event"] == "stage_start"]
        done = [e["stage"] for e in events if e["event"] == "stage_done"]
        self.assertEqual(
            started,
            ["script", "voiceover", "captions", "image-prompts", "images", "render", "publish"],
        )
        self.assertEqual(done, started)
        for event in events:
            if event["event"] == "stage_done":
                self.assertGreaterEqual(event["seconds"], 0)

    def test_notes_include_title_and_watch_url(self):
        events = []
        self._run(events.append)
        notes = [e["message"] for e in events if e["event"] == "note"]
        self.assertIn("title: T", notes)
        self.assertIn("https://www.youtube.com/watch?v=vidXYZ", notes)

    def test_pipeline_done_event_carries_total(self):
        events = []
        self._run(events.append, upload=False)
        done_events = [e for e in events if e["event"] == "pipeline_done"]
        self.assertEqual(len(done_events), 1)
        self.assertGreater(done_events[0]["total_seconds"], 0)

    def test_tracker_can_consume_real_pipeline_events(self):
        tracker = StageTracker()
        self._run(tracker.handle, upload=False)
        self.assertTrue(tracker.done)
        self.assertEqual(
            [stage for stage, _ in tracker.done_stages()],
            ["script", "voiceover", "captions", "image-prompts", "images", "render"],
        )


if __name__ == "__main__":
    unittest.main()

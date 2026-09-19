import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from clipforge.cli import build_parser, main, run_pipeline
from clipforge.pipeline.script_gen import VideoScript


class FakeStages:
    def __init__(self, tmp):
        self.tmp = tmp
        self.calls = []

    def make_config(self):
        return MagicMock()

    def fake_script(self, config, prompt, video_duration="30"):
        self.calls.append(("script", prompt, video_duration))
        return VideoScript(title="Test title", caption="Test caption", script="Narration.")

    def fake_voiceover(self, config, text, output_path, **kwargs):
        self.calls.append(("voiceover", text))
        output_path.write_bytes(b"mp3")
        return output_path

    def fake_captions(self, config, audio_path, output_path):
        self.calls.append(("captions", audio_path.name))
        output_path.write_text(json.dumps({"timed_captions": []}))
        return output_path

    def fake_prompts(self, config, script, num_images, **kwargs):
        self.calls.append(("prompts", num_images))
        return [f"prompt {i}" for i in range(num_images)]

    def fake_images(self, config, prompts, output_dir, **kwargs):
        self.calls.append(("images", prompts))
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for index in range(len(prompts)):
            path = output_dir / f"scene_{index:02d}.png"
            path.write_bytes(b"png")
            paths.append(path)
        return paths

    def fake_render(self, images, voiceover, captions, output_path, **kwargs):
        self.calls.append(("render", len(images)))
        output_path.write_bytes(b"mp4")
        return output_path

    def fake_publish(self, **kwargs):
        self.calls.append(("publish", kwargs))
        return {"id": "vidABC123"}


def _patched(fake, upload_module="clipforge.cli.publish_video"):
    patches = {
        "clipforge.cli.generate_script": fake.fake_script,
        "clipforge.cli.generate_voiceover": fake.fake_voiceover,
        "clipforge.cli.generate_timed_captions": fake.fake_captions,
        "clipforge.cli.generate_image_prompts": fake.fake_prompts,
        "clipforge.cli.generate_images": fake.fake_images,
        "clipforge.cli.render_video": fake.fake_render,
        upload_module: fake.fake_publish,
    }
    return {target: patch(target, fn) for target, fn in patches.items()}


class RunPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name) / "run"
        self.fake = FakeStages(self.tmp.name)

    def _run(self, **kwargs):
        defaults = {
            "config": self.fake.make_config(),
            "prompt": "a video about tea",
            "output_dir": self.run_dir,
            "youtube": MagicMock(),
        }
        defaults.update(kwargs)
        with patch.dict("sys.modules", {}):
            patches = _patched(self.fake)
            for p in patches.values():
                p.start()
                self.addCleanup(p.stop)
            return run_pipeline(**defaults)

    def test_full_pipeline_runs_all_stages_in_order(self):
        self._run()
        stage_order = [call[0] for call in self.fake.calls]
        self.assertEqual(
            stage_order, ["script", "voiceover", "captions", "prompts", "images", "render", "publish"]
        )

    def test_prompt_flows_to_script_generation(self):
        self._run()
        self.assertEqual(self.fake.calls[0][1], "a video about tea")

    def test_artifacts_written_to_run_dir(self):
        self._run(num_images=2)
        self.assertEqual(
            sorted(p.name for p in self.run_dir.iterdir()),
            ["captions.json", "images", "prompts.json", "publish.json", "script.json", "short.mp4", "voiceover.mp3"],
        )
        script = json.loads((self.run_dir / "script.json").read_text())
        self.assertEqual(script["title"], "Test title")
        prompts = json.loads((self.run_dir / "prompts.json").read_text())
        self.assertEqual(len(prompts), 2)

    def test_upload_scheduled_24h_out_by_default(self):
        summary = self._run()
        publish_kwargs = self.fake.calls[-1][1]
        expected = datetime.now(timezone.utc) + timedelta(hours=24)
        self.assertLess(abs((publish_kwargs["publish_at"] - expected).total_seconds()), 600)
        self.assertEqual(publish_kwargs["title"], "Test title")
        self.assertEqual(publish_kwargs["description"], "Test caption")
        self.assertEqual(summary["watch_url"], "https://www.youtube.com/watch?v=vidABC123")
        self.assertEqual(json.loads((self.run_dir / "publish.json").read_text())["video_id"], "vidABC123")

    def test_publish_in_hours_moves_schedule(self):
        self._run(publish_in_hours=48)
        publish_kwargs = self.fake.calls[-1][1]
        expected = datetime.now(timezone.utc) + timedelta(hours=48)
        self.assertLess(abs((publish_kwargs["publish_at"] - expected).total_seconds()), 600)

    def test_publish_now_clears_publish_at(self):
        self._run(publish_now=True)
        self.assertIsNone(self.fake.calls[-1][1]["publish_at"])

    def test_no_upload_skips_publish(self):
        summary = self._run(upload=False)
        self.assertNotIn("publish", [call[0] for call in self.fake.calls])
        self.assertIsNone(summary["publish_response"])
        self.assertFalse((self.run_dir / "publish.json").exists())

    def test_stage_failure_propagates_and_skips_publish(self):
        def broken_images(config, prompts, output_dir, **kwargs):
            raise RuntimeError("FLUX down")

        self.fake.fake_images = broken_images
        with self.assertRaises(RuntimeError):
            self._run()
        self.assertNotIn("publish", [call[0] for call in self.fake.calls])


class CliArgTests(unittest.TestCase):
    def test_defaults(self):
        args = build_parser().parse_args(["some prompt"])
        self.assertEqual(args.prompt, "some prompt")
        self.assertEqual(args.num_images, 3)
        self.assertEqual(args.duration, "30")
        self.assertEqual(args.publish_in_hours, 24)
        self.assertFalse(args.publish_now)
        self.assertFalse(args.no_upload)
        self.assertIsNone(args.output_dir)

    def test_all_flags_parsed(self):
        args = build_parser().parse_args(
            [
                "p",
                "--num-images",
                "5",
                "--duration",
                "60-90",
                "--publish-in-hours",
                "48",
                "--publish-now",
                "--no-upload",
                "--output-dir",
                "/tmp/x",
            ]
        )
        self.assertEqual(args.num_images, 5)
        self.assertEqual(args.duration, "60-90")
        self.assertEqual(args.publish_in_hours, 48)
        self.assertTrue(args.publish_now)
        self.assertTrue(args.no_upload)
        self.assertEqual(args.output_dir, Path("/tmp/x"))


class MainTests(unittest.TestCase):
    def test_main_success_returns_zero_and_wires_args(self):
        with patch("clipforge.cli.load_config") as load_config, patch(
            "clipforge.cli.run_pipeline"
        ) as run_pipeline:
            run_pipeline.return_value = {}
            code = main(["prompt text", "--num-images", "2", "--no-upload"])
        self.assertEqual(code, 0)
        positional, kwargs = run_pipeline.call_args
        self.assertEqual(positional[1], "prompt text")
        self.assertEqual(kwargs["num_images"], 2)
        self.assertFalse(kwargs["upload"])

    def test_main_failure_returns_one(self):
        with patch("clipforge.cli.load_config"), patch(
            "clipforge.cli.run_pipeline", side_effect=RuntimeError("boom")
        ):
            self.assertEqual(main(["p"]), 1)

    def test_main_default_output_dir_under_runs(self):
        with patch("clipforge.cli.load_config"), patch(
            "clipforge.cli.run_pipeline", return_value={}
        ) as run_pipeline:
            main(["p"])
        run_dir = run_pipeline.call_args[0][2]
        self.assertEqual(run_dir.parent.name, "runs")
        self.assertTrue(run_dir.name.startswith("run-"))


if __name__ == "__main__":
    unittest.main()

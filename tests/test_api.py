import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from clipforge.api import app, client_ip
from clipforge.pipeline.images import MIN_AUTO_IMAGES
from clipforge.pipeline.script_gen import VideoScript


def _sse_events(response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runs_dir_patcher = patch("clipforge.api.RUNS_DIR", Path(self.tmp.name))
        self.runs_dir_patcher.start()
        self.addCleanup(self.runs_dir_patcher.stop)
        self.client = TestClient(app)

    def _run_generate(self, prompt="a curious cat", num_images=2, send_num_images=True):
        with (
            patch("clipforge.api.check_and_increment", return_value=(True, 1)),
            patch("clipforge.cli.generate_script") as fake_script,
            patch("clipforge.cli.generate_voiceover") as fake_voiceover,
            patch("clipforge.cli.generate_timed_captions") as fake_captions,
            patch("clipforge.cli.generate_image_prompts") as fake_prompts,
            patch("clipforge.cli.generate_images") as fake_images,
            patch("clipforge.cli.render_video") as fake_render,
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
            fake_prompts.return_value = ["p1", "p2"]
            fake_images.side_effect = lambda config, prompts, out, **kw: []
            fake_render.side_effect = lambda *args, **kw: args[-1].write_bytes(b"mp4") or args[-1]

            payload = {
                "prompt": prompt,
                "openai_api_key": "sk-test",
                "replicate_api_token": "r8-test",
            }
            if send_num_images:
                payload["num_images"] = num_images

            response = self.client.post("/api/generate", json=payload)
            return response, fake_script, fake_prompts

    def test_health_ok(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_generate_streams_stage_events_then_result(self):
        response, fake_script, _ = self._run_generate()
        self.assertEqual(response.status_code, 200)
        events = _sse_events(response)

        started = [e["stage"] for e in events if e["event"] == "stage_start"]
        self.assertEqual(
            started, ["script", "voiceover", "captions", "image-prompts", "images", "render"]
        )

        result_events = [e for e in events if e["event"] == "result"]
        self.assertEqual(len(result_events), 1)
        self.assertIn("video_url", result_events[0])

        config_used = fake_script.call_args.args[0]
        self.assertEqual(config_used.openai_api_key, "sk-test")
        self.assertEqual(config_used.replicate_api_token, "r8-test")

    def test_omitted_num_images_resolves_automatically(self):
        # fake_script's "Narration." is one sentence, so auto count clamps to
        # MIN_AUTO_IMAGES (3) - see clipforge.pipeline.images.auto_image_count.
        response, _, fake_prompts = self._run_generate(send_num_images=False)
        self.assertEqual(response.status_code, 200)
        events = _sse_events(response)
        self.assertEqual([e for e in events if e["event"] == "error"], [])
        prompts_call_kwargs = fake_prompts.call_args
        self.assertEqual(prompts_call_kwargs.args[-1], MIN_AUTO_IMAGES)
        notes = [e["message"] for e in events if e["event"] == "note"]
        self.assertTrue(any("auto image count" in note for note in notes))

    def test_generate_serves_the_rendered_video(self):
        response, _, _ = self._run_generate()
        events = _sse_events(response)
        video_url = next(e["video_url"] for e in events if e["event"] == "result")

        video_response = self.client.get(video_url)
        self.assertEqual(video_response.status_code, 200)
        self.assertEqual(video_response.content, b"mp4")

    def test_missing_run_video_returns_404(self):
        response = self.client.get("/api/runs/does-not-exist/video")
        self.assertEqual(response.status_code, 404)

    def test_quota_block_stops_before_running_pipeline(self):
        with (
            patch("clipforge.api.check_and_increment", return_value=(False, 100)),
            patch("clipforge.cli.generate_script") as fake_script,
        ):
            response = self.client.post(
                "/api/generate",
                json={
                    "prompt": "x",
                    "openai_api_key": "sk-test",
                    "replicate_api_token": "r8-test",
                },
            )
            events = _sse_events(response)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event"], "error")
            self.assertIn("100", events[0]["message"])
            fake_script.assert_not_called()

    def test_pipeline_failure_emits_error_event(self):
        with (
            patch("clipforge.api.check_and_increment", return_value=(True, 1)),
            patch("clipforge.cli.generate_script", side_effect=RuntimeError("boom")),
        ):
            response = self.client.post(
                "/api/generate",
                json={
                    "prompt": "x",
                    "openai_api_key": "sk-test",
                    "replicate_api_token": "r8-test",
                },
            )
            events = _sse_events(response)
            self.assertEqual(events[-1], {"event": "error", "message": "boom"})


class ClientIpTests(unittest.TestCase):
    def test_prefers_forwarded_header(self):
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        self.assertEqual(client_ip(request), "1.2.3.4")

    def test_falls_back_to_direct_client(self):
        request = MagicMock()
        request.headers = {}
        request.client.host = "9.9.9.9"
        self.assertEqual(client_ip(request), "9.9.9.9")

    def test_no_client_returns_none(self):
        request = MagicMock()
        request.headers = {}
        request.client = None
        self.assertIsNone(client_ip(request))


if __name__ == "__main__":
    unittest.main()

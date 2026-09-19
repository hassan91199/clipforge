import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from clipforge.config import Config
from clipforge.pipeline.images import (
    generate_image,
    generate_image_prompts,
    generate_images,
)


def _config():
    return Config(
        openai_api_key="test-openai-key",
        replicate_api_token="test-replicate-token",
        google_client_id="",
        google_client_secret="",
        google_redirect_uri="",
    )


def _http_response(status_code, body=None, headers=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body if body is not None else {}
    response.headers = headers or {}
    response.text = text
    return response


def _chat_response(prompts):
    return _http_response(
        200,
        {"choices": [{"message": {"content": json.dumps({"prompts": prompts})}}]},
    )


class TestGenerateImagePrompts(unittest.TestCase):
    @patch("clipforge.pipeline.images.requests.post")
    def test_parses_structured_response(self, mock_post):
        mock_post.return_value = _chat_response(["Scene one", "Scene two", "Scene three"])

        prompts = generate_image_prompts(_config(), "narration text", 3)

        self.assertEqual(prompts, ["Scene one", "Scene two", "Scene three"])
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "gpt-4o-2024-08-06")
        system_message = payload["messages"][0]["content"]
        self.assertIn("exactly 3 scenes", system_message)
        self.assertIn("photorealistic", system_message)
        schema = payload["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["prompts"]["minItems"], 3)
        self.assertEqual(schema["properties"]["prompts"]["maxItems"], 3)

    @patch("clipforge.pipeline.images.requests.post")
    def test_rejects_wrong_prompt_count(self, mock_post):
        mock_post.return_value = _chat_response(["Scene one", "Scene two"])

        with self.assertRaises(RuntimeError) as context:
            generate_image_prompts(_config(), "narration text", 3)

        self.assertIn("Expected 3 image prompts, got 2", str(context.exception))

    def test_requires_api_key(self):
        config = _config()
        object.__setattr__(config, "openai_api_key", "")
        with self.assertRaises(RuntimeError):
            generate_image_prompts(config, "narration text", 3)


class TestGenerateImage(unittest.TestCase):
    @patch("clipforge.pipeline.images.requests.get")
    @patch("clipforge.pipeline.images.requests.request")
    def test_downloads_image_to_output_path(self, mock_request, mock_get):
        mock_request.side_effect = [
            _http_response(201, {"id": "pred-123"}),
            _http_response(200, {"status": "succeeded", "output": "https://img.example/x.png"}),
        ]
        mock_get.return_value = _http_response(200)
        mock_get.return_value.content = b"png-bytes"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "scene_00.png"
            result = generate_image(_config(), "an octopus scene", output_path)

            self.assertEqual(result, output_path)
            self.assertEqual(output_path.read_bytes(), b"png-bytes")

        create_args = mock_request.call_args_list[0].args
        create_kwargs = mock_request.call_args_list[0].kwargs
        self.assertEqual(
            create_args,
            ("POST", "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"),
        )
        self.assertEqual(create_kwargs["json"]["input"]["prompt"], "an octopus scene")
        self.assertEqual(create_kwargs["json"]["input"]["aspect_ratio"], "9:16")
        self.assertEqual(
            create_kwargs["headers"]["Authorization"], "Bearer test-replicate-token"
        )
        self.assertEqual(
            mock_request.call_args_list[1].args,
            ("GET", "https://api.replicate.com/v1/predictions/pred-123"),
        )
        self.assertEqual(mock_get.call_args.args[0], "https://img.example/x.png")

    @patch("clipforge.pipeline.images.requests.get")
    @patch("clipforge.pipeline.images.requests.request")
    def test_accepts_list_output(self, mock_request, mock_get):
        mock_request.side_effect = [
            _http_response(201, {"id": "pred-1"}),
            _http_response(200, {"status": "succeeded", "output": ["https://img.example/y.png"]}),
        ]
        mock_get.return_value = _http_response(200)
        mock_get.return_value.content = b"png-bytes"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "scene_00.png"
            generate_image(_config(), "prompt", output_path)
            self.assertEqual(output_path.read_bytes(), b"png-bytes")

        self.assertEqual(mock_get.call_args.args[0], "https://img.example/y.png")


    @patch("clipforge.pipeline.images.time.sleep")
    @patch("clipforge.pipeline.images.requests.get")
    @patch("clipforge.pipeline.images.requests.request")
    def test_retries_on_rate_limit(self, mock_request, mock_get, mock_sleep):
        mock_request.side_effect = [
            _http_response(429, headers={"Retry-After": "1"}),
            _http_response(201, {"id": "pred-2"}),
            _http_response(200, {"status": "succeeded", "output": "https://img.example/z.png"}),
        ]
        mock_get.return_value = _http_response(200)
        mock_get.return_value.content = b"png-bytes"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "scene_00.png"
            generate_image(_config(), "prompt", output_path)
            self.assertEqual(output_path.read_bytes(), b"png-bytes")

        self.assertEqual(mock_request.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertEqual(mock_sleep.call_args.args[0], 2)

    @patch("clipforge.pipeline.images.time.sleep")
    @patch("clipforge.pipeline.images.requests.get")
    @patch("clipforge.pipeline.images.requests.request")
    def test_polls_until_succeeded(self, mock_request, mock_get, mock_sleep):
        mock_request.side_effect = [
            _http_response(201, {"id": "pred-3"}),
            _http_response(200, {"status": "starting"}),
            _http_response(200, {"status": "processing"}),
            _http_response(200, {"status": "succeeded", "output": "https://img.example/w.png"}),
        ]
        mock_get.return_value = _http_response(200)
        mock_get.return_value.content = b"png-bytes"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "scene_00.png"
            generate_image(_config(), "prompt", output_path)
            self.assertEqual(output_path.read_bytes(), b"png-bytes")

        self.assertEqual(mock_request.call_count, 4)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("clipforge.pipeline.images.requests.get")
    @patch("clipforge.pipeline.images.requests.request")
    def test_raises_on_failed_prediction(self, mock_request, mock_get):
        mock_request.side_effect = [
            _http_response(201, {"id": "pred-4"}),
            _http_response(200, {"status": "failed", "error": "upstream unavailable"}),
        ]

        with self.assertRaises(RuntimeError) as context:
            generate_image(_config(), "prompt", Path("/tmp/scene.png"))

        self.assertIn("Image generation failed: upstream unavailable", str(context.exception))
        mock_get.assert_not_called()

    @patch("clipforge.pipeline.images.requests.get")
    @patch("clipforge.pipeline.images.requests.request")
    def test_raises_on_unexpected_output(self, mock_request, mock_get):
        mock_request.side_effect = [
            _http_response(201, {"id": "pred-5"}),
            _http_response(200, {"status": "succeeded", "output": 42}),
        ]

        with self.assertRaises(RuntimeError) as context:
            generate_image(_config(), "prompt", Path("/tmp/scene.png"))

        self.assertIn("unexpected output", str(context.exception))

    def test_requires_replicate_token(self):
        config = _config()
        object.__setattr__(config, "replicate_api_token", "")
        with self.assertRaises(RuntimeError):
            generate_image(config, "prompt", Path("/tmp/scene.png"))


class TestGenerateImages(unittest.TestCase):
    @patch("clipforge.pipeline.images.generate_image")
    def test_preserves_prompt_order(self, mock_generate):
        def fake(config, prompt, output_path, **kwargs):
            output_path.write_bytes(prompt.encode())
            return output_path

        mock_generate.side_effect = fake

        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = generate_images(_config(), ["alpha", "beta", "gamma"], Path(tmp_dir))
            self.assertEqual(
                [path.name for path in paths], ["scene_00.png", "scene_01.png", "scene_02.png"]
            )
            self.assertEqual([path.read_text() for path in paths], ["alpha", "beta", "gamma"])

    @patch("clipforge.pipeline.images.time.sleep")
    @patch("clipforge.pipeline.images.generate_image")
    def test_retries_failed_scene(self, mock_generate, mock_sleep):
        results = {"scene_01.png": False}

        def fake(config, prompt, output_path, **kwargs):
            if output_path.name == "scene_01.png" and not results[output_path.name]:
                results[output_path.name] = True
                raise RuntimeError("boom")
            output_path.write_bytes(prompt.encode())
            return output_path

        mock_generate.side_effect = fake

        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = generate_images(_config(), ["alpha", "beta"], Path(tmp_dir))
            self.assertEqual(len(paths), 2)
            self.assertEqual((Path(tmp_dir) / "scene_01.png").read_text(), "beta")

        self.assertEqual(mock_generate.call_count, 3)

    @patch("clipforge.pipeline.images.time.sleep")
    @patch("clipforge.pipeline.images.generate_image")
    def test_fails_loudly_when_scene_exhausts_attempts(self, mock_generate, mock_sleep):
        mock_generate.side_effect = RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(RuntimeError) as context:
                generate_images(_config(), ["alpha", "beta"], Path(tmp_dir))

        self.assertIn("failed for 2 of 2 scenes", str(context.exception))
        self.assertIn("indices: [0, 1]", str(context.exception))
        self.assertEqual(mock_generate.call_count, 6)

    @patch("clipforge.pipeline.images.generate_image")
    def test_empty_prompts_return_no_paths(self, mock_generate):
        self.assertEqual(generate_images(_config(), [], Path("/tmp")), [])
        mock_generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
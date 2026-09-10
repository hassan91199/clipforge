import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from clipforge.config import Config
from clipforge.pipeline.tts import generate_voiceover


def _config():
    return Config(
        openai_api_key="test-key",
        replicate_api_token="",
        google_client_id="",
        google_client_secret="",
        google_redirect_uri="",
    )


class TestGenerateVoiceover(unittest.TestCase):
    @patch("clipforge.pipeline.tts.requests.post")
    def test_generate_voiceover_writes_audio_file(self, mock_post):
        mock_response = MagicMock()
        mock_response.content = b"fake-audio-bytes"
        mock_post.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "voiceover.mp3"
            result = generate_voiceover(
                _config(), "Did you know octopuses have three hearts?", output_path
            )

            self.assertEqual(result, output_path)
            self.assertEqual(output_path.read_bytes(), b"fake-audio-bytes")

        called_kwargs = mock_post.call_args.kwargs
        self.assertEqual(called_kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(called_kwargs["json"]["voice"], "alloy")
        self.assertEqual(called_kwargs["json"]["model"], "tts-1")
        self.assertEqual(called_kwargs["json"]["input"], "Did you know octopuses have three hearts?")

    def test_generate_voiceover_requires_api_key(self):
        config = _config()
        object.__setattr__(config, "openai_api_key", "")
        with self.assertRaises(RuntimeError):
            generate_voiceover(config, "text", Path("/tmp/out.mp3"))


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from unittest.mock import MagicMock, patch

from clipforge.config import Config
from clipforge.pipeline.script_gen import generate_script


def _config():
    return Config(
        openai_api_key="test-key",
        replicate_api_token="",
        google_client_id="",
        google_client_secret="",
        google_redirect_uri="",
    )


class TestGenerateScript(unittest.TestCase):
    @patch("clipforge.pipeline.script_gen.requests.post")
    def test_generate_script_parses_structured_response(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "script": "Did you know octopuses have three hearts?",
                                "title": "3 Hearts, 1 Octopus",
                                "caption": "Wild ocean facts. #shorts #ocean",
                            }
                        )
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        result = generate_script(_config(), "a fun fact about octopuses", video_duration="30")

        self.assertEqual(result.script, "Did you know octopuses have three hearts?")
        self.assertEqual(result.title, "3 Hearts, 1 Octopus")
        self.assertEqual(result.caption, "Wild ocean facts. #shorts #ocean")

        called_kwargs = mock_post.call_args.kwargs
        self.assertEqual(called_kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(called_kwargs["json"]["model"], "gpt-4o-2024-08-06")

    def test_generate_script_requires_api_key(self):
        config = _config()
        object.__setattr__(config, "openai_api_key", "")
        with self.assertRaises(RuntimeError):
            generate_script(config, "a fun fact about octopuses")


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from clipforge.config import Config
from clipforge.pipeline.captions import (
    generate_timed_captions,
    get_timed_captions,
    map_segments_to_time,
    merge_small_captions,
    segment_sentences,
    split_sentences,
    split_to_words,
    to_srt,
    transcribe,
)


def _config():
    return Config(
        openai_api_key="test-key",
        replicate_api_token="",
        google_client_id="",
        google_client_secret="",
        google_redirect_uri="",
    )


def _whisper_response():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "text": "Octopuses have three hearts. Two pump blood to the gills.",
        "duration": 3.51,
        "words": [
            {"word": "Octopuses", "start": 0.01, "end": 0.86},
            {"word": "have", "start": 0.86, "end": 1.12},
            {"word": "three", "start": 1.12, "end": 1.5},
            {"word": "hearts.", "start": 1.5, "end": 1.91},
            {"word": "Two", "start": 1.91, "end": 2.23},
            {"word": "pump", "start": 2.23, "end": 2.54},
            {"word": "blood", "start": 2.54, "end": 2.91},
            {"word": "to", "start": 2.91, "end": 3.12},
            {"word": "the", "start": 3.12, "end": 3.31},
            {"word": "gills.", "start": 3.31, "end": 3.51},
        ],
    }
    return response


class TestTranscribe(unittest.TestCase):
    @patch("clipforge.pipeline.captions.requests.post")
    def test_transcribe_returns_rounded_word_timestamps(self, mock_post):
        mock_post.return_value = _whisper_response()

        with tempfile.NamedTemporaryFile(suffix=".mp3") as audio_file:
            analysis = transcribe(_config(), Path(audio_file.name))

        self.assertEqual(analysis["duration"], 3.51)
        self.assertEqual(analysis["text"], "Octopuses have three hearts. Two pump blood to the gills.")
        self.assertEqual(analysis["words"][0], {"word": "Octopuses", "start": 0.01, "end": 0.86})
        self.assertEqual(len(analysis["words"]), 10)

        called_kwargs = mock_post.call_args.kwargs
        self.assertEqual(called_kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(called_kwargs["data"]["model"], "whisper-1")
        self.assertEqual(called_kwargs["data"]["timestamp_granularities[]"], "word")
        self.assertEqual(called_kwargs["data"]["response_format"], "verbose_json")

    @patch("clipforge.pipeline.captions.time.sleep")
    @patch("clipforge.pipeline.captions.requests.post")
    def test_transcribe_retries_then_succeeds(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            requests.exceptions.RequestException("boom"),
            requests.exceptions.RequestException("boom"),
            _whisper_response(),
        ]

        with tempfile.NamedTemporaryFile(suffix=".mp3") as audio_file:
            analysis = transcribe(_config(), Path(audio_file.name))

        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertEqual(analysis["duration"], 3.51)

    @patch("clipforge.pipeline.captions.time.sleep")
    @patch("clipforge.pipeline.captions.requests.post")
    def test_transcribe_raises_after_max_retries(self, mock_post, mock_sleep):
        mock_post.side_effect = requests.exceptions.RequestException("down")

        with tempfile.NamedTemporaryFile(suffix=".mp3") as audio_file:
            with self.assertRaises(RuntimeError) as context:
                transcribe(_config(), Path(audio_file.name))

        self.assertIn("failed after 5 attempts", str(context.exception))
        self.assertEqual(mock_post.call_count, 5)

    def test_transcribe_requires_api_key(self):
        config = _config()
        object.__setattr__(config, "openai_api_key", "")
        with self.assertRaises(RuntimeError):
            transcribe(config, Path("/tmp/out.mp3"))


class TestCaptionSplitting(unittest.TestCase):
    def test_split_sentences(self):
        self.assertEqual(
            split_sentences("One fact. Really? Yes!"),
            ["One fact.", "Really?", "Yes!"],
        )

    def test_segment_sentences_splits_at_spaces(self):
        self.assertEqual(
            segment_sentences(["Octopuses have three hearts."]),
            ["Octopuses have three", "hearts."],
        )

    def test_segment_sentences_hard_breaks_long_words(self):
        self.assertEqual(
            segment_sentences(["Supercalifragilisticexpialidocious"]),
            ["Supercalifragilistic", "expialidocious"],
        )

    def test_split_to_words_handles_hyphens_and_contractions(self):
        self.assertEqual(
            split_to_words("A state-of-the-art don't-miss clip"),
            ["A", "state", "of", "the", "art", "don't", "miss", "clip"],
        )


class TestMapSegmentsToTime(unittest.TestCase):
    def test_maps_segments_to_word_timings(self):
        words = [
            {"word": "Octopuses", "start": 0.01, "end": 0.86},
            {"word": "have", "start": 0.86, "end": 1.12},
            {"word": "three", "start": 1.12, "end": 1.5},
        ]
        self.assertEqual(
            map_segments_to_time(words, ["Octopuses have three"]),
            [((0.01, 1.5), "Octopuses have three")],
        )

    def test_raises_when_segment_words_cannot_match(self):
        words = [{"word": "alpha", "start": 0.0, "end": 1.0}]
        with self.assertRaises(ValueError):
            map_segments_to_time(words, ["beta gamma"])


class TestMergeSmallCaptions(unittest.TestCase):
    def test_merges_short_caption_into_shorter_adjacent_text(self):
        self.assertEqual(
            merge_small_captions(
                [
                    ((0.0, 1.0), "Hello"),
                    ((1.0, 1.1), "there"),
                    ((1.1, 2.0), "friend"),
                ]
            ),
            [((0.0, 1.1), "Hello there"), ((1.1, 2.0), "friend")],
        )

    def test_merges_short_first_caption_forward(self):
        self.assertEqual(
            merge_small_captions(
                [
                    ((0.0, 0.1), "Hi"),
                    ((0.1, 1.5), "everyone"),
                ]
            ),
            [((0.0, 1.5), "Hi everyone")],
        )


class TestGetTimedCaptions(unittest.TestCase):
    def test_builds_timed_captions_from_whisper_analysis(self):
        analysis = _whisper_response().json.return_value
        self.assertEqual(
            get_timed_captions(analysis),
            [
                ((0.01, 1.5), "Octopuses have three"),
                ((1.5, 1.91), "hearts."),
                ((1.91, 3.12), "Two pump blood to"),
                ((3.12, 3.51), "the gills."),
            ],
        )


class TestGenerateTimedCaptions(unittest.TestCase):
    @patch("clipforge.pipeline.captions.requests.post")
    def test_writes_json_track_and_srt_sibling(self, mock_post):
        mock_post.return_value = _whisper_response()

        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = Path(tmp_dir) / "voiceover.mp3"
            audio_path.write_bytes(b"fake-audio")
            output_path = Path(tmp_dir) / "captions.json"
            result = generate_timed_captions(_config(), audio_path, output_path)

            self.assertEqual(result, output_path)

            track = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(track["duration"], 3.51)
            self.assertEqual(
                track["timed_captions"][1], {"start": 1.5, "end": 1.91, "text": "hearts."}
            )
            self.assertEqual(len(track["words"]), 10)

            srt_text = output_path.with_suffix(".srt").read_text(encoding="utf-8")
            self.assertIn("00:00:00,010 --> 00:00:01,500", srt_text)
            self.assertIn("hearts.", srt_text)

        called_kwargs = mock_post.call_args.kwargs
        self.assertEqual(called_kwargs["headers"]["Authorization"], "Bearer test-key")

    def test_to_srt_formats_intervals(self):
        srt_text = to_srt([((1.5, 2.91), "Two pump blood to")])
        self.assertIn("00:00:01,500 --> 00:00:02,910", srt_text)
        self.assertIn("Two pump blood to", srt_text)


if __name__ == "__main__":
    unittest.main()
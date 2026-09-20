"""Voiceover audio -> timed caption data (OpenAI Whisper).

Adapted from CloakMotion's vid-gen app/audio/audio_utils.py (audioToText +
getRoundedWhisperAnalysis) and app/editing_utils/captions.py (getTimedCaptions
and its helpers) - same endpoint, payload shape and caption-chunking logic,
minus the ApiKeyManager DB lookup (reuses OPENAI_API_KEY already required for
CF-3/CF-4) and the timed-segments pass the demo's render doesn't need.

Writes a JSON caption track plus a sibling .srt for CF-7 to burn into the
final render.
"""

import json
import re
import string
import time
from datetime import timedelta
from pathlib import Path

import requests
import srt

from clipforge.config import Config

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"

DEFAULT_MODEL = "whisper-1"
DEFAULT_MAX_CAPTION_SIZE = 20
DEFAULT_MIN_CAPTION_DURATION = 0.25
DEFAULT_MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 3
TIMESTAMP_DECIMALS = 2


def transcribe(config: Config, audio_path: Path, max_retries: int = DEFAULT_MAX_RETRIES) -> dict:
    """Transcribe audio to word-level timestamps via OpenAI Whisper."""
    config.require("openai_api_key")

    last_error = None
    for attempt in range(max_retries):
        try:
            with open(audio_path, "rb") as audio_file:
                response = requests.post(
                    OPENAI_TRANSCRIPTIONS_URL,
                    headers={"Authorization": f"Bearer {config.openai_api_key}"},
                    files={"file": (Path(audio_path).name, audio_file)},
                    data={
                        "timestamp_granularities[]": "word",
                        "model": DEFAULT_MODEL,
                        "response_format": "verbose_json",
                    },
                    timeout=120,
                )
                response.raise_for_status()
                analysis = response.json()
                return {
                    "text": analysis["text"],
                    "duration": round(analysis["duration"], TIMESTAMP_DECIMALS),
                    "words": [
                        {
                            "word": word["word"],
                            "start": round(word["start"], TIMESTAMP_DECIMALS),
                            "end": round(word["end"], TIMESTAMP_DECIMALS),
                        }
                        for word in analysis["words"]
                    ],
                }
        except requests.exceptions.RequestException as error:
            last_error = error
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Whisper transcription failed after {max_retries} attempts: {last_error}")


def split_sentences(text: str) -> list[str]:
    segments = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in segments if s.strip()]


def segment_sentences(sentences: list[str], max_len: int = DEFAULT_MAX_CAPTION_SIZE) -> list[str]:
    segments = []
    for sentence in sentences:
        i = 0
        while i < len(sentence):
            if len(sentence) - i <= max_len:
                segments.append(sentence[i:].strip())
                break

            chunk = sentence[i : i + max_len + 1]
            split_index = max_len
            if not chunk[max_len].isspace() and chunk[max_len - 1].isspace():
                split_index = max_len - 1
            elif chunk[max_len].isspace() and not chunk[max_len - 1].isspace():
                split_index = max_len
            elif not chunk[max_len].isspace() and not chunk[max_len - 1].isspace():
                last_space = chunk[:max_len].rfind(" ")
                if last_space != -1:
                    split_index = last_space

            segments.append(sentence[i : i + split_index].strip())
            i += split_index
            while i < len(sentence) and sentence[i] == " ":
                i += 1
    return segments


def split_to_words(sentence: str) -> list[str]:
    sentence = sentence.replace("-", " ")
    return re.findall(r"\b\w+(?:'\w+)?\b", sentence)


def map_segments_to_time(
    words_with_time: list[dict], sentence_segments: list[str]
) -> list[tuple[tuple[float, float], str]]:
    result = []
    words_queue = words_with_time.copy()

    for segment in sentence_segments:
        segment_words = split_to_words(segment)
        cleaned_words = [w.strip(string.punctuation) for w in segment_words]

        start_time = None
        matched_indices = []

        for i, word_info in enumerate(words_queue):
            if word_info["word"].strip(string.punctuation).lower() == cleaned_words[0].lower():
                start_time = word_info["start"]
                matched_indices.append(i)
                break

        word_idx = 1
        i = matched_indices[0] + 1 if matched_indices else 0
        while i < len(words_queue) and word_idx < len(cleaned_words):
            if (
                words_queue[i]["word"].strip(string.punctuation).lower()
                == cleaned_words[word_idx].lower()
            ):
                matched_indices.append(i)
                word_idx += 1
            i += 1

        if word_idx == len(cleaned_words) and matched_indices:
            end_time = words_queue[matched_indices[-1]]["end"]
            result.append(((start_time, end_time), segment))
            for idx in reversed(matched_indices):
                del words_queue[idx]
        else:
            raise ValueError(f"Could not match all words for segment: '{segment}'")

    return result


def merge_small_captions(
    timed_captions: list[tuple[tuple[float, float], str]],
    min_duration: float = DEFAULT_MIN_CAPTION_DURATION,
) -> list[tuple[tuple[float, float], str]]:
    captions = timed_captions[:]
    i = 0
    while i < len(captions):
        (start, end), text = captions[i]
        if end - start >= min_duration:
            i += 1
            continue

        prev_caption = captions[i - 1] if i > 0 else None
        next_caption = captions[i + 1] if i < len(captions) - 1 else None

        merge_with = None
        if prev_caption and next_caption:
            prev_merge_len = len(prev_caption[1] + " " + text)
            next_merge_len = len(text + " " + next_caption[1])
            merge_with = "prev" if prev_merge_len <= next_merge_len else "next"
        elif prev_caption:
            merge_with = "prev"
        elif next_caption:
            merge_with = "next"

        if merge_with == "prev":
            (p_start, _), p_text = captions[i - 1]
            captions[i - 1] = ((p_start, end), p_text + " " + text)
            captions.pop(i)
            i -= 1
        elif merge_with == "next":
            (_, n_end), n_text = captions[i + 1]
            captions[i + 1] = ((start, n_end), text + " " + n_text)
            captions.pop(i)
        else:
            i += 1
    return captions


def get_timed_captions(
    whisper_analysis: dict,
    max_caption_size: int = DEFAULT_MAX_CAPTION_SIZE,
    min_duration: float = DEFAULT_MIN_CAPTION_DURATION,
) -> list[tuple[tuple[float, float], str]]:
    sentences = split_sentences(whisper_analysis.get("text", ""))
    segments = segment_sentences(sentences, max_len=max_caption_size)
    timed_captions = map_segments_to_time(whisper_analysis.get("words", []), segments)
    return merge_small_captions(timed_captions, min_duration)


def to_srt(timed_captions: list[tuple[tuple[float, float], str]]) -> str:
    subtitles = [
        srt.Subtitle(
            index=index,
            start=timedelta(seconds=start),
            end=timedelta(seconds=end),
            content=text,
        )
        for index, ((start, end), text) in enumerate(timed_captions)
    ]
    return srt.compose(subtitles)


def generate_timed_captions(config: Config, audio_path: Path, output_path: Path) -> Path:
    """Transcribe the voiceover and save the timed caption track to output_path."""
    analysis = transcribe(config, audio_path)
    timed_captions = get_timed_captions(analysis)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "text": analysis["text"],
                "duration": analysis["duration"],
                "words": analysis["words"],
                "timed_captions": [
                    {"start": start, "end": end, "text": text}
                    for (start, end), text in timed_captions
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    output_path.with_suffix(".srt").write_text(to_srt(timed_captions), encoding="utf-8")
    return output_path

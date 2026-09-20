"""Prompt -> short-form video script generation (GPT-4o).

Adapted from CloakMotion's vid-gen/app/gpt/gpt_chat_video.py::generateScript
and gpt_yt.py::generate_title_description_dict, combined into a single call -
this demo has no series/multi-step editing flow to justify two round trips.
"""

import json
from dataclasses import dataclass

import requests

from clipforge.config import Config

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# Matches CloakMotion's word_count_map: target word count per target duration,
# so the generated script reads back in roughly that many seconds at natural pace.
_WORD_COUNT_BY_DURATION = {
    "30": 85,
    "30-60": 128,
    "60-90": 213,
}


@dataclass(frozen=True)
class VideoScript:
    title: str
    caption: str
    script: str


def generate_script(config: Config, prompt: str, video_duration: str = "30") -> VideoScript:
    """Generate a narration script + YouTube title/caption from a raw prompt."""
    config.require("openai_api_key")
    word_count = _WORD_COUNT_BY_DURATION.get(video_duration, 85)

    system_message = (
        "You are an AI that generates high-quality short-form video content based on a "
        f"user prompt, for a {video_duration} second video of about {word_count} words. "
        "Return: "
        "1) 'script' - narration text only, no scene directions, camera cues, or "
        "formatting, just continuous spoken text a voice actor reads aloud. "
        "2) 'title' - a short, attention-grabbing YouTube Shorts title (under 100 characters). "
        "3) 'caption' - a YouTube description/caption "
        "(1-3 sentences, may include relevant hashtags). "
        "Keep the language simple, concise, and engaging from start to finish."
    )

    json_schema = {
        "name": "video_script_schema",
        "schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "Narration-only script text."},
                "title": {"type": "string", "description": "YouTube Shorts title."},
                "caption": {"type": "string", "description": "YouTube description/caption."},
            },
            "required": ["script", "title", "caption"],
            "additionalProperties": False,
        },
    }

    response = requests.post(
        OPENAI_CHAT_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.openai_api_key}",
        },
        json={
            "model": "gpt-4o-2024-08-06",
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_schema", "json_schema": json_schema},
        },
        timeout=60,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    return VideoScript(
        title=data["title"].strip(),
        caption=data["caption"].strip(),
        script=data["script"].strip(),
    )

"""Script -> voiceover audio (OpenAI TTS).

Adapted from CloakMotion's vid-gen/app/audio/openai_voice_module.py - same
endpoint and payload shape, but a plain function instead of the VoiceModule
ABC/factory (this demo has exactly one TTS provider, no ElevenLabs fallback
to swap in, and reuses OPENAI_API_KEY already required for CF-3).
"""

from pathlib import Path

import requests

from clipforge.config import Config

OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

DEFAULT_VOICE = "alloy"
DEFAULT_MODEL = "tts-1"


def generate_voiceover(
    config: Config,
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    model: str = DEFAULT_MODEL,
) -> Path:
    """Generate a voiceover audio file from script text and save it to output_path."""
    config.require("openai_api_key")

    response = requests.post(
        OPENAI_TTS_URL,
        headers={
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": text,
            "voice": voice,
        },
        timeout=60,
    )
    response.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    return output_path

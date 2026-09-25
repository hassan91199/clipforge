"""Script -> scene images (GPT-4o prompts -> Replicate FLUX).

Adapted from CloakMotion's vid-gen app/api_utils/replicate_api.py
(ReplicateAPI.generate_image + generate_image_urls_replicate, including its
retry/backoff and output-normalization fixes) and the GPT-4o prompt step
(dalle_api.generate_simple_prompts / EnhancedPromptGenerator). Differences:
ClipForge is prompt-driven (no stock-footage search terms), so image prompts
come straight from the CF-3 script in one GPT-4o call; the Replicate token
comes from env config instead of the ApiKeyManager DB; and images download
to a plain local directory instead of the storage-backend factory.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from clipforge.config import Config
from clipforge.pipeline.captions import split_sentences

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
REPLICATE_API_URL = "https://api.replicate.com/v1"

DEFAULT_FLUX_MODEL = "black-forest-labs/flux-schnell"
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_STYLE = "photorealistic"

MIN_AUTO_IMAGES = 3
MAX_AUTO_IMAGES = 8


def auto_image_count(script: str) -> int:
    """Derive a scene count from the script's own sentence structure.

    Deterministic, not an LLM guess - mirrors CloakMotion's segment-per-
    sentence approach (one image per natural narration beat) rather than
    asking a model to invent a number. Clamped so a one-line script still
    gets a few scenes and a long one doesn't blow up render time/cost.
    """
    sentence_count = len(split_sentences(script))
    return max(MIN_AUTO_IMAGES, min(sentence_count, MAX_AUTO_IMAGES))


REQUEST_TIMEOUT = (10, 60)
PREDICTION_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 2
MAX_RETRY_WAIT_SECONDS = 30
RETRY_BASE_DELAY_SECONDS = 2
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504, 520, 522, 524}


def generate_image_prompts(
    config: Config, script: str, num_images: int, style: str = DEFAULT_STYLE
) -> list[str]:
    """Split a narration script into image prompts (one per scene) via GPT-4o."""
    config.require("openai_api_key")

    system_message = (
        "You are an AI that converts narration scripts into image prompts for a short-form video. "
        f"Split the script into exactly {num_images} scenes and write one image prompt per scene. "
        "Each prompt describes a single still image illustrating the narration at that point: "
        "concrete subject, setting, composition, and lighting. "
        f"Keep a consistent visual style across all scenes: {style}. "
        "Never include text, letters, logos, or captions in the image. "
        "Each prompt must be a single vivid sentence under 60 words."
    )
    json_schema = {
        "name": "image_prompts_schema",
        "schema": {
            "type": "object",
            "properties": {
                "prompts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": num_images,
                    "maxItems": num_images,
                },
            },
            "required": ["prompts"],
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
                {"role": "user", "content": script},
            ],
            "response_format": {"type": "json_schema", "json_schema": json_schema},
        },
        timeout=60,
    )
    response.raise_for_status()

    prompts = [
        prompt.strip()
        for prompt in json.loads(response.json()["choices"][0]["message"]["content"])["prompts"]
    ]
    if len(prompts) != num_images or any(not prompt for prompt in prompts):
        raise RuntimeError(f"Expected {num_images} image prompts, got {len(prompts)}")
    return prompts


def _retry_wait(attempt: int, response) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after) + 1, MAX_RETRY_WAIT_SECONDS)
            except (TypeError, ValueError):
                pass
    return min(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_RETRY_WAIT_SECONDS)


def _request_with_retries(method: str, url: str, max_retries: int, **kwargs):
    last_error = None
    response = None
    for attempt in range(1, max_retries + 1):
        try:
            kwargs.setdefault("timeout", REQUEST_TIMEOUT)
            response = requests.request(method, url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as error:
            last_error, response = error, None
        else:
            if response.status_code not in RETRYABLE_STATUS:
                return response
            last_error = f"HTTP {response.status_code}"

        if attempt < max_retries:
            time.sleep(_retry_wait(attempt, response))

    if response is not None:
        return response
    raise RuntimeError(f"Request to {url} failed after {max_retries} attempts: {last_error}")


def _extract_output_url(output) -> str:
    if isinstance(output, str):
        url = output
    elif isinstance(output, (list, tuple)) and output:
        url = output[0]
    else:
        url = None

    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise RuntimeError(f"Replicate returned an unexpected output: {output!r}")
    return url


def _poll_prediction(prediction_url: str, headers: dict) -> str:
    deadline = time.time() + PREDICTION_TIMEOUT_SECONDS
    while True:
        if time.time() > deadline:
            raise RuntimeError(
                f"Prediction did not complete within {PREDICTION_TIMEOUT_SECONDS} seconds"
            )
        response = _request_with_retries("GET", prediction_url, max_retries=10, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(
                f"Unexpected error during prediction status check: HTTP {response.status_code}"
            )
        data = response.json()
        status = data.get("status")
        if status == "succeeded":
            return _extract_output_url(data.get("output"))
        if status == "failed":
            raise RuntimeError(f"Image generation failed: {data.get('error')}")
        if status in ("starting", "processing"):
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        raise RuntimeError(f"Unexpected prediction status: {status}")


def generate_image(
    config: Config,
    prompt: str,
    output_path: Path,
    model: str = DEFAULT_FLUX_MODEL,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> Path:
    """Generate one image via Replicate FLUX and download it to output_path."""
    config.require("replicate_api_token")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.replicate_api_token}",
    }

    response = _request_with_retries(
        "POST",
        f"{REPLICATE_API_URL}/models/{model}/predictions",
        max_retries=10,
        headers=headers,
        json={
            "input": {
                "prompt": prompt,
                "go_fast": True,
                "megapixels": "1",
                "num_outputs": 1,
                "aspect_ratio": aspect_ratio,
                "output_format": "png",
                "output_quality": 100,
                "num_inference_steps": 4,
            }
        },
    )
    if response.status_code != 201:
        raise RuntimeError(
            f"Replicate image request failed with status {response.status_code}: {response.text}"
        )

    prediction_url = f"{REPLICATE_API_URL}/predictions/{response.json()['id']}"
    image_url = _poll_prediction(prediction_url, headers)

    image = requests.get(image_url, timeout=REQUEST_TIMEOUT)
    image.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image.content)
    return output_path


def generate_images(
    config: Config,
    prompts: list[str],
    output_dir: Path,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    max_concurrency: int = 3,
    max_attempts: int = 3,
) -> list[Path]:
    """Generate an image per prompt into output_dir, preserving prompt order."""
    if not prompts:
        return []

    def process(indexed_prompt):
        index, prompt = indexed_prompt
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                output_path = Path(output_dir) / f"scene_{index:02d}.png"
                generate_image(config, prompt, output_path, aspect_ratio=aspect_ratio)
                return index, output_path
            except Exception as error:
                last_error = error
                if attempt < max_attempts:
                    time.sleep(3 * attempt)
        return index, last_error

    workers = min(max_concurrency, len(prompts)) or 1
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for index, result in executor.map(process, enumerate(prompts)):
            results.append((index, result))

    failures = {index: error for index, error in results if not isinstance(error, Path)}
    if failures:
        raise RuntimeError(
            f"Image generation failed for {len(failures)} of {len(prompts)} scenes "
            f"(indices: {sorted(failures)}): {next(iter(failures.values()))}"
        )
    return [path for _, path in sorted(results)]

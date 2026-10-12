"""Synthesize per-scene narration + per-phrase caption timings from demo/script.json.

Writes demo/build/<scene-id>.mp3 and demo/build/timings.json (phrase start/end
seconds per scene, relative to that scene's own clip). Run before record.py.
"""

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import edge_tts

ROOT = Path(__file__).parent
BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)


def cache_key(voice: str, text: str) -> str:
    return hashlib.sha256(f"{voice}|{text}".encode()).hexdigest()[:16]


async def synthesize(voice: str, text: str, out_mp3: Path) -> list[tuple[float, float]]:
    """Returns word (start, end) seconds via WordBoundary events."""
    comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    words: list[tuple[float, float]] = []
    with out_mp3.open("wb") as audio:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((start, start + chunk["duration"] / 1e7))
    return words


async def synthesize_with_retry(voice: str, text: str, out_mp3: Path, max_attempts: int = 4):
    wait = 20
    for attempt in range(1, max_attempts + 1):
        try:
            return await synthesize(voice, text, out_mp3)
        except Exception as exc:  # edge-tts can 403 on bursts; retry with backoff
            if attempt == max_attempts:
                raise
            print(f"  synth attempt {attempt} failed ({exc}); retrying in {wait}s")
            await asyncio.sleep(wait)
            wait *= 2


def clip_duration(mp3: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(mp3)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


async def main():
    script = json.loads((ROOT / "script.json").read_text())
    voice = script["voice"]
    timings: dict[str, dict] = {}

    for scene in script["scenes"]:
        scene_id = scene["id"]
        phrases = scene["phrases"]
        text = " ".join(phrases)
        key = cache_key(voice, text)
        mp3 = BUILD / f"{scene_id}.mp3"
        cache_marker = BUILD / f"{scene_id}.{key}.cached"

        if mp3.exists() and cache_marker.exists():
            print(f"{scene_id}: cached")
            words = json.loads(cache_marker.read_text())["words"]
        else:
            print(f"{scene_id}: synthesizing ({len(phrases)} phrases)")
            words = await synthesize_with_retry(voice, text, mp3)
            cache_marker.write_text(json.dumps({"words": words}))
            await asyncio.sleep(3)  # space out requests to avoid 403 bursts

        total_words = sum(len(p.split()) for p in phrases)
        assert len(words) == total_words, (
            f"{scene_id}: expected {total_words} word events, got {len(words)}"
        )

        phrase_spans = []
        idx = 0
        for phrase in phrases:
            n = len(phrase.split())
            phrase_words = words[idx: idx + n]
            phrase_spans.append({
                "text": phrase,
                "start": phrase_words[0][0],
                "end": phrase_words[-1][1],
            })
            idx += n

        timings[scene_id] = {
            "duration": clip_duration(mp3),
            "phrases": phrase_spans,
        }

    (BUILD / "timings.json").write_text(json.dumps(timings, indent=2))
    print("wrote demo/build/timings.json")


if __name__ == "__main__":
    asyncio.run(main())

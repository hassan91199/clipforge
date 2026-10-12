"""Record the real Next.js UI against the narration cues from synth.py.

Requires the local stack already running (see README: uvicorn clipforge.api:app
--port 8080, cd frontend && npm run dev) and demo/build/timings.json present.
Writes demo/build/video/*.webm (raw, via Playwright's recordVideo), end-of-scene
screenshots to demo/build/screenshots/, and cue start times to demo/build/cues.json.
"""

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parent
BUILD = ROOT / "build"
VIDEO_DIR = BUILD / "video"
SCREENSHOTS_DIR = BUILD / "screenshots"
VIDEO_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)

FRONTEND_URL = "http://localhost:3001"
VIEWPORT = {"width": 1440, "height": 900}

CURSOR_INIT_SCRIPT = """
const dot = document.createElement('div');
dot.style.position = 'fixed';
dot.style.zIndex = '999999';
dot.style.width = '14px';
dot.style.height = '14px';
dot.style.borderRadius = '50%';
dot.style.background = 'rgba(255, 90, 90, 0.9)';
dot.style.border = '2px solid white';
dot.style.pointerEvents = 'none';
dot.style.left = '-100px';
dot.style.top = '-100px';
dot.style.transition = 'left 0.05s linear, top 0.05s linear';
document.addEventListener('DOMContentLoaded', () => document.body.appendChild(dot));
window.addEventListener('mousemove', (e) => {
  dot.style.left = (e.clientX - 7) + 'px';
  dot.style.top = (e.clientY - 7) + 'px';
});
"""


def load_env(env_path: Path) -> dict:
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def move_and_click(page, locator):
    box = locator.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=30)
    locator.click()


def hold_until(scene_start: float, min_elapsed: float, wait_fn=None):
    """Runs wait_fn() (if given, e.g. a selector wait) then tops up the hold
    so the scene lasts at least min_elapsed seconds (narration duration + 1s),
    even if the real UI event it's narrating about already happened."""
    if wait_fn is not None:
        wait_fn()
    remaining = min_elapsed - (time.time() - scene_start)
    if remaining > 0:
        time.sleep(remaining)


def main():
    timings = json.loads((BUILD / "timings.json").read_text())
    env = load_env(PROJECT_ROOT / ".env")

    cues: dict[str, float] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
        context = browser.new_context(
            viewport=VIEWPORT,
            color_scheme="dark",
            record_video_dir=str(VIDEO_DIR),
            record_video_size=VIEWPORT,
        )
        context.add_init_script(CURSOR_INIT_SCRIPT)
        page = context.new_page()
        t0 = time.time()  # recording clock starts here, per the playbook

        def cue(scene_id: str) -> float:
            offset = time.time() - t0
            cues[scene_id] = offset
            print(f"{scene_id}: cue at {offset:.2f}s")
            return offset

        # ---- scene: intro ----
        scene_start = time.time()
        cue("intro")
        page.goto(FRONTEND_URL)
        page.wait_for_selector("#prompt")

        prompt_box = page.locator("#prompt")
        move_and_click(page, prompt_box)
        prompt_box.type("Why the sky is blue, for curious kids", delay=25)

        openai_box = page.locator("#openai-key")
        move_and_click(page, openai_box)
        openai_box.type(env["OPENAI_API_KEY"], delay=5)

        replicate_box = page.locator("#replicate-token")
        move_and_click(page, replicate_box)
        replicate_box.type(env["REPLICATE_API_TOKEN"], delay=5)

        auto_images = page.locator("#auto-images")
        move_and_click(page, auto_images)  # uncheck -> reveals the manual slider

        num_images = page.locator("#num-images")
        num_images.focus()
        page.keyboard.press("ArrowRight")  # 3 -> 4

        submit = page.locator("button[type=submit]")
        move_and_click(page, submit)

        page.screenshot(path=str(SCREENSHOTS_DIR / "intro.png"))
        hold_until(
            scene_start,
            timings["intro"]["duration"] + 1.0,
            wait_fn=lambda: page.wait_for_selector("[data-status]", timeout=30_000),
        )

        # ---- scene: fast-stages (script / voiceover / captions / image-prompts) ----
        scene_start = time.time()
        cue("fast-stages")
        hold_until(
            scene_start,
            timings["fast-stages"]["duration"] + 1.0,
            wait_fn=lambda: page.wait_for_selector(
                '[data-status]:has-text("images")', timeout=60_000
            ),
        )
        page.screenshot(path=str(SCREENSHOTS_DIR / "fast-stages.png"))

        # ---- scene: images (the long real wait - FLUX rendering) ----
        scene_start = time.time()
        cue("images")
        hold_until(
            scene_start,
            timings["images"]["duration"] + 1.0,
            wait_fn=lambda: page.wait_for_selector(
                '[data-status="done"]:has-text("images")', timeout=180_000
            ),
        )
        page.screenshot(path=str(SCREENSHOTS_DIR / "images.png"))

        # ---- scene: result (render + finished video) ----
        scene_start = time.time()
        cue("result")
        page.wait_for_selector("video", timeout=120_000)
        video = page.locator("video")
        # The finished video is a tall 9:16 player; at 1440x900 it sits below
        # the fold unless scrolled into view, so the recording would never
        # actually show it.
        video.scroll_into_view_if_needed()
        video.evaluate("el => { el.muted = true; el.play(); }")
        remaining = timings["result"]["duration"] + 1.0 - (time.time() - scene_start)
        if remaining > 0:
            time.sleep(remaining)
        time.sleep(2)  # let it visibly play a beat after narration ends
        page.screenshot(path=str(SCREENSHOTS_DIR / "result.png"))

        context.close()  # flushes the raw .webm
        browser.close()

    (BUILD / "cues.json").write_text(json.dumps(cues, indent=2))
    print("wrote demo/build/cues.json")
    print("raw video in demo/build/video/")


if __name__ == "__main__":
    main()

"""Browser tests with Playwright: the real app in a real browser.

The Playwright tier complements the AppTest tier (tests/test_app.py) with the
things AppTest cannot see: the actual websocket streaming of stage rows into
the DOM, a st.video element that really loads (duration > 0), and real
widget behavior like textarea commit-on-blur.

The harness boots the real Streamlit server on localhost with run_pipeline
stubbed at clipforge.cli *before* ui.py imports it, so the app is exercised
as shipped while costing zero API calls. Runs only when RUN_BROWSER_TESTS=1
(and playwright is installed), so the default suite stays fast and hermetic.
"""

import http.client
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from playwright.sync_api import expect

RUNNER_ENV = os.environ.get("RUN_BROWSER_TESTS") == "1"
try:
    from playwright.sync_api import sync_playwright

    HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover - depends on local install
    HAS_PLAYWRIGHT = False

REPO_ROOT = Path(__file__).resolve().parents[1]

CONFIG_ENV = {
    "OPENAI_API_KEY": "test-openai",
    "REPLICATE_API_TOKEN": "test-replicate",
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
}

STAGES = ["script", "voiceover", "captions", "image-prompts", "images", "render"]

# The wrapper streamlit executes. It swaps run_pipeline at clipforge.cli
# *before* ui.py imports it, so the app binds the stub. Events carry small
# sleeps so the websocket streaming is exercised like a real run.
WRAPPER_TEMPLATE = """
import os
import shutil
import time
from pathlib import Path

import clipforge.cli as cli

VIDEO = Path(os.environ["CF_BROWSER_VIDEO"])


def fake_run_pipeline(config, prompt, output_dir, num_images=3,
                      video_duration="30", publish_in_hours=24, upload=False,
                      publish_now=False, youtube=None, on_event=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(VIDEO, output_dir / "short.mp4")
    for stage in {stages!r}:
        on_event({{"event": "stage_start", "stage": stage}})
        time.sleep(0.05)
        on_event({{"event": "stage_done", "stage": stage, "seconds": 1.5}})
    on_event({{"event": "note", "message": "title: Fake title"}})
    on_event({{"event": "pipeline_done", "total_seconds": 10.0}})
    return {{
        "title": "Fake title",
        "total_seconds": 10.0,
        "watch_url": "",
        "video_path": VIDEO,
    }}


cli.run_pipeline = fake_run_pipeline
import clipforge.ui as ui  # noqa: E402

ui.render_app()
""".format(stages=STAGES)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _tiny_mp4(path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.2:size=128x128:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def _wait_healthy(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", "/_stcore/health")
            if conn.getresponse().read() == b"ok":
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("streamlit server did not become healthy in time")


@unittest.skipUnless(
    RUNNER_ENV and HAS_PLAYWRIGHT,
    "browser tier is opt-in: RUN_BROWSER_TESTS=1 with playwright installed",
)
class BrowserTests(unittest.TestCase):
    """One Streamlit server for the class; each test drives a fresh page."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.video = _tiny_mp4(Path(cls.tmp.name) / "short.mp4")
        cls.wrapper = Path(cls.tmp.name) / "browser_stub_app.py"
        cls.wrapper.write_text(WRAPPER_TEMPLATE)
        cls.port = _free_port()
        env = dict(os.environ)
        env.update(CONFIG_ENV)
        env["CF_BROWSER_VIDEO"] = str(cls.video)
        cls.server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(cls.wrapper),
                "--server.port",
                str(cls.port),
                "--server.headless",
                "true",
                "--server.fileWatcherType",
                "none",
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_healthy(cls.port)
        cls._playwright = sync_playwright().start()
        cls.browser = cls._playwright.chromium.launch()
        # class cleanups run LIFO: stop playwright last, after the browser.
        cls.addClassCleanup(cls._playwright.stop)
        cls.addClassCleanup(cls.browser.close)

        def stop_server():
            cls.server.terminate()
            try:
                cls.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.server.kill()

        cls.addClassCleanup(stop_server)
        cls.addClassCleanup(cls.tmp.cleanup)

    def _open_page(self):
        page = self.browser.new_page()
        page.goto(f"http://127.0.0.1:{self.port}")
        page.wait_for_selector("textarea", timeout=30000)
        self.addCleanup(page.close)
        return page

    def _generate(self, page):
        prompt = page.get_by_label("Video prompt")
        prompt.fill("Why is the sky blue, for kids")
        prompt.press("Tab")  # streamlit commits textarea on blur
        page.get_by_role("button", name="Generate video").click()

    def test_stage_rows_stream_and_total_appears(self):
        page = self._open_page()
        self._generate(page)
        success = page.get_by_text("Fake title - 10.0s total")
        success.wait_for(timeout=30000)
        for stage in STAGES:
            page.get_by_text(f"{stage} - 1.5s").first.wait_for(timeout=5000)
        page.get_by_text("Total: 10.0s").wait_for(timeout=5000)
        self.assertTrue(success.is_visible())

    def test_video_element_really_loads(self):
        page = self._open_page()
        self._generate(page)
        page.wait_for_selector("video", timeout=30000)
        page.wait_for_function(
            "() => { const v = document.querySelector('video');"
            " return v && isFinite(v.duration) && v.duration > 0; }",
            timeout=15000,
        )
        duration = page.evaluate("() => document.querySelector('video').duration")
        self.assertGreater(duration, 0)

    def test_button_disabled_until_prompt_committed(self):
        page = self._open_page()
        button = page.get_by_role("button", name="Generate video")
        self.assertTrue(button.is_disabled())
        prompt = page.get_by_label("Video prompt")
        prompt.fill("prompt")
        prompt.press("Tab")
        # streamlit reruns after the blur; expect() retries until it lands.
        expect(button).to_be_enabled(timeout=10000)


if __name__ == "__main__":
    unittest.main()

# ClipForge agent conventions

Operating rules for anyone (or any agent) working in this repo. The ClickUp
workflow lives in CLAUDE.md; this file covers how code changes are made.

## Testing: test-first is the default workflow

For every bug fix or feature, work in this order:

1. **RED** — write the test that captures the new behavior or reproduces the
   bug. Run it and confirm it fails for the expected reason.
2. **GREEN** — implement the smallest change that makes the full suite pass.
3. **REFACTOR** — clean up with the suite green, re-run `scripts/test.sh`
   before committing.

Never commit implementation without the test that pins it. Never weaken an
assertion, a coverage floor, or a lint rule to make a change fit.

## Test layers (what goes where)

| Layer | Location | Runs via | Cost per run | What belongs here |
| --- | --- | --- | --- | --- |
| Unit | `tests/test_*.py` | in-process, stage fakes | free | Each stage module's logic in isolation |
| Integration | `tests/test_cli.py` (`FakeStages`), `tests/test_ui.py` (event contract) | full `run_pipeline` with all-fake stages | free | Orchestration: stage order, artifacts, event stream, failure propagation |
| App/browser | `tests/test_app.py` | Streamlit AppTest driving `clipforge/ui.py` | free | Widget interaction and rendered output of the UI |
| Container | `docker run --rm clipforge` | same suite inside the image | free | Env parity: deps, entrypoint, permissions |
| Real smoke | manual, or CF-16 CI job | live APIs | ~$0.10/run | Explicitly requested before a release; never part of the default suite |

Rules that keep the suite hermetic:

- **No network calls in tests, ever.** External APIs are patched with fakes.
  If a test needs the real thing, it is a smoke test and does not live here.
- Tests never depend on the host's `.env` — they patch env vars explicitly.
- AppTest quirks worth remembering: the app script is **exec'd** per run, so
  stub `clipforge.cli.run_pipeline` (not `clipforge.ui.run_pipeline`);
  `set_value()` needs an explicit `.run()` to mimic browser commit-on-blur;
  `st.empty()` placeholder content is not recorded, prefer direct `st.error`.
- A tiny mp4 fixture is generated with `ffmpeg -f lavfi testsrc` (no fixture
  files in the repo).

## Commands

```sh
.venv/bin/python scripts/test.sh   # lint + format + full suite under coverage
docker run --rm clipforge          # same gate inside the container
.venv/bin/ruff format clipforge tests scripts   # format
```

Coverage floor is `95` for the `clipforge/` package (`pyproject.toml`).
Baseline is 96% (2026-09-20, CF-15). Raise the floor when coverage grows;
never lower it to land a change.

## Style

- `ruff` with `E,F,W,I` at line length 100; `ruff format` is the formatter.
  Both are checked in the same gate as the tests.
- Python 3.12, stdlib `unittest` (not pytest) — match existing test style:
  one class per concern, `tempfile.TemporaryDirectory` for artifacts, `patch`
  with explicit targets.
- Comments explain *why*; code and test names explain *what*.
- Dependencies: runtime pins in `requirements.txt`, dev tools in
  `requirements-dev.txt`. Both installed in the Docker image so the container
  gate matches local.

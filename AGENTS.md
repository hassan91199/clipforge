# ClipForge agent conventions

Operating rules for anyone (or any agent) working in this repo.

## ClickUp task workflow

Tasks for this project live in the ClickUp list **proj-clipforge**
(`list_id: 1100390000016137`, under Space "Hassan's Space" > Folder "Portfolio
Project") — same pattern as **proj-swiftreels** (`list_id: 901807349061`) and
**proj-cloakmotion** (`list_id: 1100390000013942`) in that folder. Use this
workflow whenever asked to create a task here, without re-asking for these
details.

### Naming and numbering

- Every task is titled `CF-<N> <short title>`, where `<N>` is one more than
  the highest existing CF number in the workspace.
- To find the current highest `<N>`: `clickup_search` with
  `keywords: "CF-"`, `filters.asset_types: ["task"]`. Results are **not**
  sorted numerically and are paginated — follow every `next_cursor` until it
  comes back `null`, then take the max `N` parsed from all titles seen.

### Status

- Leave `status` unset on creation (list default applies) unless the user
  says where the task should start.
- Statuses below are carried over from proj-cloakmotion's identical setup in
  the same folder, not yet confirmed for this list (ClickUp API was
  rate-limited when this file was written — verify with `clickup_get_list`
  before relying on this): `Open`, `on hold`, `ongoing`, `queued`,
  `in progress`, `completed`, `Closed`. Match the user's wording to these
  exactly (case-sensitive) — "move to queue" → `queued`, "move to in
  progress" → `in progress". If they say "mark it done" and it's ambiguous
  between `completed` and `Closed`, ask.

### Description and priority

- Write `markdown_description` with a `## Problem`/`## Scope` structure
  when there's enough context — cite concrete evidence (error messages,
  file paths) for the problem, and list concrete files/dirs in scope.
- If the task is unclear enough to need target decisions the user hasn't
  given yet, add an `## Open questions` section rather than guessing —
  create the task anyway so it's tracked, but don't invent specifics.
- Default `priority` to `normal` unless told otherwise.

## Git branches

- Never commit directly to `main`. All work happens on a branch; `main`
  only ever changes by merging a branch into it (`git merge --no-ff`, then
  push `main`). Never force-push.
- **Pushing/`gh` write ops**: this machine has multiple GitHub accounts, and
  the default session is not the one that owns this repo (`hassan91199`). A
  plain `git push` fails with a misleading "Repository not found" instead of
  pointing at the fix. Always prefix with the matching wrapper:
  `as-hassan-personal git push origin main` (same pattern for any `gh`
  write command). Full multi-account setup:
  `~/dev/projs/github-hassan91199/personal-docs/docs/git-github-auth.md`.
  This applies regardless of which coding agent is driving the command.
- If the work is tracked by a ClickUp ticket, the branch is named `cf-<N>`
  matching that ticket's **actual** number — never invent the "next
  sequential number" as a branch name when no ticket backs it (CloakMotion
  hit this exact problem with an orphaned `srt-58` branch; same risk applies
  here with `cf-<N>`).
- If told **not** to file a ClickUp task for a piece of work (e.g. a quick
  bug fix):
  - If a branch for the current task/conversation is already checked out
    and in progress, do the work there.
  - Otherwise, create a new branch, but name it for what the work actually
    is (not an invented `cf-<N>`), e.g. `fix-caption-timing-offset`.
  - Either way, still merge into `main` the normal way when done.

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
| Browser (real) | `tests/test_browser.py` | Playwright vs a live Streamlit server (`scripts/browser_test.sh`) | free | What AppTest cannot see: websocket streaming into the DOM, video element really loading, blur-commit |
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
- The two browser tiers split by what only a real browser can prove: AppTest
  owns the interaction contract (fast, runs in every gate); Playwright owns
  rendering and websocket behavior (video duration > 0, stage rows arriving
  incrementally). Playwright is opt-in via `scripts/browser_test.sh`, kept
  out of the default gate and out of the Docker image (browser binaries
  ~400MB); pin `playwright==1.63.0` when CI wires it up (CF-16).
- A tiny mp4 fixture is generated with `ffmpeg -f lavfi testsrc` (no fixture
  files in the repo).

## Commands

```sh
.venv/bin/python scripts/test.sh   # lint + format + full suite under coverage
sh scripts/browser_test.sh         # Playwright tier (needs one-time chromium install)
docker run --rm clipforge          # same gate inside the container
sh scripts/infra_localstack.sh     # terraform gate (fmt/validate + quota apply on LocalStack)
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

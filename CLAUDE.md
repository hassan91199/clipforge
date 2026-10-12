# ClickUp task workflow (ClipForge)

Code-change conventions (test-first workflow, test layers, style) live in
[AGENTS.md](AGENTS.md) — follow them for every change in this repo.

Tasks for this project live in the ClickUp list **proj-clipforge**
(`list_id: 1100390000016137`, under Space "Hassan's Space" > Folder "Portfolio
Project") — same pattern as **proj-swiftreels** (`list_id: 901807349061`) and
**proj-cloakmotion** (`list_id: 1100390000013942`) in that folder. Use this
workflow whenever asked to create a task here, without re-asking for these
details.

## Naming and numbering

- Every task is titled `CF-<N> <short title>`, where `<N>` is one more than
  the highest existing CF number in the workspace.
- To find the current highest `<N>`: `clickup_search` with
  `keywords: "CF-"`, `filters.asset_types: ["task"]`. Results are **not**
  sorted numerically and are paginated — follow every `next_cursor` until it
  comes back `null`, then take the max `N` parsed from all titles seen.

## Status

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

## Description and priority

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

---
name: commit
description: Commits and, when authorized, pushes a reviewed set of cveta2 changes. Stages exact task-owned paths, writes Conventional Commits accepted by the commit-msg hook, and handles pre-commit rewrites and failures, including the changed-function mutation report and the live integration gate. Use when committing or pushing cveta2 changes or when a pre-commit or commit-msg hook fails.
---

# Commit cveta2 changes

General rules (inspect status and diffs, stage exact paths with
`git add -- <path>`, never stash/reset/broad-stage, no `--no-verify`) come from
`AGENTS.md` and engineering guidance. This skill adds what is specific here.

## Message

`type(scope)!: description`, lowercase type from the `conventional-pre-commit`
args in `.pre-commit-config.yaml`. Only `feat`, `fix`, `perf` and `!` move the
version (semantic-release). A `!` needs a `BREAKING CHANGE:` footer for the
changelog text. Reword git's default `Revert "..."` subject into a type.

## Hooks

`git commit` runs every gate; there is no pre-push stage, so a passing commit is
safe to push with plain `git push`. Read `.pre-commit-config.yaml` for the list.

- A hook that rewrites files (`uv lock`, `ruff format`): inspect the new diff,
  restage only task-owned paths, commit again.
- `mutmut` (when `cveta2/` changes) is advisory: it prints surviving mutants of
  the changed functions and passes. Triage them with the `mutation-testing`
  skill when the change is behavioural; it fails only on a tool error.
- `integration-tests` (when `cveta2/`, `tests/integration/`, `pyproject.toml`
  or `uv.lock` change) runs the live suite for minutes. Do not edit the checkout
  meanwhile: pre-commit holds unstaged changes stashed. A down stand, a `room`
  WAIT or an active `tests/integration/.run-tag` fails it; see the
  `running-integration-tests` skill. `SKIP=integration-tests` only on the user's
  explicit request.
- A failure caused by unrelated pre-existing work: report the exact blocker; do
  not modify, stage or discard that work.

After rebase, cherry-pick or merge (no pre-commit hook runs), run
`uv run pre-commit run --all-files` and, for the mutation report,
`uv run python scripts/mutation.py --base <upstream>` before pushing. A commit
that only deletes files runs no file-filtered hook (mutation, live gate).

## Report

Commit hash and subject, pushed ref if any (confirm with
`git ls-remote origin <ref>`), the hooks that ran and the mutation survivors
reported, and the remaining unrelated working-tree state.

# Implementation Plan: Development verification

**Branch**: `chore/simplify-hooks-20261109` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

## Summary

Implement the supplied six-stage migration: bounded feasibility evidence, Task
commands and corrected affected selection, bounded infrastructure preflight,
compatible Git staging shim, governing guidance, then integrated validation and
independent review. Task never uses freshness to skip verification.

## Technical Context

Python and uv remain governed by `pyproject.toml`. Add go-task-bin only as a dev
dependency. Taskfile owns sequential command definitions; prek retains one serial
always-selected verify hook and Conventional Commit validation. Keep native
Ruff/mypy caches and per-worktree testmon data. Compute the testmon namespace
inline from interpreter identity, locked dependencies, verification configuration,
static assets and full relative source/test membership. Python content remains
selected through testmon. No custom controller or persisted completion database.

`tests/integration/lifecycle.py` owns bounded read-only check and setup
classification; reuse existing run-tag ownership and cleanup. Preserve
`--dist loadgroup` and environment isolation. Worker count is configurable through
`CVETA2_TEST_WORKERS`. Preflight uses `CVETA2_INFRA_CHECK_TIMEOUT`, default 60 seconds.
Shared registry capacity and shared release lock remain authoritative.

## Constitution Check

Before research and after design: approved amendment 4.0.0 reconciles explicit
fixes, staging, incremental verification and infrastructure deferral. The public
baseline, dataset contract, architecture and glossary are unchanged. Spec Kit
owns this work; generated skills/templates remain unchanged. Validation uses
manual tooling experiments, not tooling-only repository tests. Final independent
review and live acceptance remain mandatory. No outstanding policy conflict.

## Project Structure

- `Taskfile.yml`, `pyproject.toml`, `uv.lock`: commands and dependencies.
- `.pre-commit-config.yaml`, `scripts/install-hooks.sh`, minimal hook shim:
  staged-input enforcement and compatible worktree hook installation.
- `tests/integration/lifecycle.py`: bounded read-only availability and startup.
- `AGENTS.md`, `.specify/memory/{constitution,engineering}.md`, authored skills,
  Russian README setup: one discoverable completion procedure.
- `docs/adr/task-verification.md`: rationale and rejected freshness caching.
- `docs/plans/task-verification-20261109/feasibility.md`: observed experiments.
- This feature: design, quality checklists, task status and dated final evidence.

## Phases and ownership

1. Disposable feasibility exercises precede production hooks. Cover selection,
   invalidation, failures, interruption, Task exit codes and shim rejection.
2. Implement Task and dependency changes, then infrastructure checks, then hooks.
   These are sequential dependencies. Documentation may be prepared separately.
3. Migrate policy and authored skills together, preserving legacy worktrees.
4. Stop all editing before integrated checks. Record actual command counts,
   selected tests, timings, outcome classifications and cleanup.
5. Fresh independent review after integration and verification. Resolve findings,
   rerun affected checks, converge against the spec, and retain deferred live
   acceptance as incomplete. Push requires separate authorization.

## Complexity Tracking

No new service, controller, shared heavy-job lock, remote cache or CI. The only
custom Git layer is the approved minimal staging shim. Markdownlint is separate.

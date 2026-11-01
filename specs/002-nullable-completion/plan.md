# Implementation Plan: Nullable completion evidence

**Branch**: `cleanup/contracts-and-release` | **Date**: 2026-11-01 | **Spec**: [spec.md](spec.md)

## Summary

Repair the reproduced baseline violation through its existing policy/effect owner.
Keep this feature distinct from the other bug family and from the
[maintenance work](../../docs/plans/full-cleanup/plan.md).

## Technical Context

Python >=3.12,<3.14; development 3.12; uv/Hatchling, pandas, Pydantic, PyYAML,
CVAT SDK and existing lockfile. No dependency changes or new public APIs.
Local pytest regressions, Ruff, strict mypy, Vulture, import-linter, effect checks,
90% coverage gate, fast/full mutation and configured live pre-push checks apply.
No new storage formats, service changes, framework migrations or deployment.

## Constitution Check

Before research and after design: PASS. Behavior delta has current spec/plan/tasks;
compatibility and task-owned scope are explicit; pure policy and outgoing effects
retain their owners; regressions precede fixes. Existing isolation, cleanup,
mutation scope and authorized Git-only release stay intact. No violations.

## Architecture

[architecture.json](architecture.json) inventories inspected modules, interfaces,
allowed/forbidden dependencies and effect ownership. Existing exhaustive inward
layers, effect/SDK ownership and forbidden-edge negative fixtures cover the changed
modules. No new module or relaxed dependency exception is justified. Validate plan
before implementation and acceptance after integrated checks and fresh review.

## Project Structure and Ownership

Canonical changes: `cveta2/domain/partition.py`.
Regressions: `tests/test_partition.py`. One bounded implementer owns those files; the parent
owns shared baseline/docs, mutation equivalent reconciliation, integrated checks,
final review and release. Independent bug streams and test maintenance can run
in parallel after architecture planning; shared artifacts remain parent-owned.

## Acceptance and Documentation

Run `uv run pytest tests/test_partition.py tests/test_whats_new.py`, then the integrated static/coverage/architecture gates.
Run fast/full mutation without reducing scope; triage only demonstrated changes.
The configured integration gate remains required for delivery. Update baseline
and relevant user guidance; record dated results, original failure evidence,
review and convergence in evidence/verification-2026-11-01.md.

The companion portable skill at published commit
`13766a1ecb36fdc584cc7588f39ba713155753bc` already documents current usage.
These fixes restore specified behavior without command/signature/default changes;
its dirty, stale local checkout needs no edits or installation.

Complete task commits, merge to main, evaluate semantic-release and push commits
and any resulting Git tag after gates. Preserve the pre-existing two untracked
skill links and prior committed fetch-delivery receipt. No GitHub Release objects.

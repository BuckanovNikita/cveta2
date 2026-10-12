# Implementation Plan: Fetch without validation

**Branch**: `feat/fetch-skip-validation-integrated` | **Date**: 2026-10-12
**Spec**: [spec.md](spec.md)

## Summary

Add an opt-in service preflight that accepts eligible jobs in CVAT before normal
fetch lists tasks. Reuse CVAT port operations, worker limits and normal partitioning.

## Technical Context

Python 3.10+ CLI/library; existing uv, pytest, Ruff, mypy, import-linter and
mutation tooling. Storage: CVAT jobs, configured task cache on disk/S3, CSV output.
No dependencies or configuration fields are added. Parallel task work is bounded
by Workers.cvat; jobs within a task update sequentially. No latency target.

## Constitution Check

Pre-research and post-design: PASS. Spec precedes implementation. Services own
orchestration; CLI/API map arguments. No SDK imports leave _client. CSV contracts
and default paths remain unchanged. Specific errors cross service boundaries.
New code uses no future annotations import. Unit/live/mutation/doc/static checks
are planned. Unrelated work is excluded; shared resources use owned tags and
exact cleanup. Authorized release uses semantic-release and Git tags only.

## Project Structure

- cveta2/cli.py, commands/fetch.py, api.py: flag, echo and keyword forwarding.
- cveta2/services/fetch.py: FetchOptions and project-only promotion barrier.
- cveta2/task_cache.py: optional strict invalidation, leaving normal cache policy.
- tests/test_fetch_skip_validation.py: fake-port state, barriers and recovery.
- tests/test_api.py, test_cli_parsing.py: adapter contracts.
- tests/integration/test_fetch_skip_validation.py: owned live CVAT scenario.
- README.md, docs/cli.md, docs/python-api.md, docs/images-and-cache.md:
  Russian user behavior; shared architecture/dataset contract in English.
- Feature artifacts: spec, plan, research, data-model, contracts, quickstart,
  checklists, tasks and dated evidence.

## Design

fetch_project invokes a promotion helper only when enabled, before _fetch_core.
List project tasks without completed-only, remove ignored IDs, inspect every job.
A task must have jobs, all state=completed, stage in annotation/acceptance.
Only annotation jobs are patched to stage=acceptance/state=completed.
run_concurrent bounds task processing; updates within each task stay sequential.
Failures identify project/task or task/job and raise Cveta2Error; executor waits
for in-flight work before returning. No annotation/output work starts on failure.

Build invalidation cache with CacheConfig.load(options.config_path), including
project tasks_root and task_cache_s3 override. Local entries are invalidated even
when cache reads/writes are disabled; S3 is touched only when cache is enabled.
Strictly invalidate before first PATCH so deletion failure leaves task unchanged,
and any later PATCH failure already has no stale cache. Strict S3 deletion raises
instead of disabling silently; normal cache operations keep existing defaults.
Fresh task listing and fresh cache reads after the barrier observe CVAT state.

## Workstreams and Dependencies

Parent owns adapters, service/cache implementation, unit verification and integration.
After the contract is fixed, documentation and live-test authoring can proceed in
parallel in disjoint files. Live execution follows implementation. Full checks
precede fresh independent review; fixes require verification and renewed review.
Convergence precedes authorized Conventional Commit, merge to main and tag release.

## Verification

Nearest unit tests first, then full pytest (includes docs), Ruff, mypy,
lint-imports, fast/full mutation profiles under the mutation skill, and configured
commit/push gates. Live scenario under the integration skill proves job state,
CVAT task completion, completed-only membership, default-off and idempotence.
Preserve fixture env isolation and exact-tag cleanup. Record results and any
unavailable checks in dated evidence; never treat unavailable checks as passing.

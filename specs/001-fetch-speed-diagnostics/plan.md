# Implementation Plan: Faster fetches and actionable CVAT errors

**Branch**: `feat/fetch-speed-diagnostics` | **Date**: 2026-10-28
**Spec**: [spec.md](spec.md)

## Summary

Remove redundant S3 probes, per-row filesystem work, debug CSV writes and task
inventories. Capture sanitized failed HTTP requests at the CVAT transport boundary
and preserve final status responses without altering retry budgets. Retain existing
public fetch signatures, formats, concurrency and stage ordering.

## Technical Context

Python >=3.12,<3.14, development 3.12; existing hatchling/uv package and CLI.
Dependencies stay pinned by uv.lock: CVAT SDK/urllib3, boto3/botocore, pandas,
Pydantic, Loguru and tenacity. Files/S3 own caches and images. Existing pytest,
Ruff, strict mypy, Vulture, import-linter, effect checker, coverage/mutation and
serial stand integration gates apply. No dependency migration or installed tooling edit.

## Constitution Check

Before research: pass. Spec defines delta from baseline, preservation and failure
policies; no unresolved user decisions. Native Spec Kit stages retained. Domain
and application stay effect-free except injected ports/clocks/runner/locks.
After design: pass. Architecture record uses existing import/effect/negative
contracts. Tests, external usage docs, independent review and release are tasks.
Pre-existing untracked skill links are excluded from all ownership/commits.

## Project Structure and Architecture

[architecture.json](architecture.json) records task-owned module effects and checks.
Domain errors own immutable `CvatRequestDiagnostics`; exceptions facade re-exports
it without a second identity. CVAT adapters own SDK interception, sanitation,
UTC clocks and translation. Execution retry owns wait/log behavior using neutral
errors. Application fetch owns complete inventory/selected-task separation and
stage/outcome accounting through existing ports and injected effects. S3 adapters
own direct GET/list fallback and request/body classification. File adapters own
confinement, cached path resolution and atomic writes. No inward SDK dependency.

The new CVAT diagnostics module encapsulates transport context and sanitation,
not application policy. Existing exhaustive layers, adapter independence, facade
exclusion, SDK ownership and negative effect/import fixtures cover these modules.

## Design and Contracts

See [research](research.md), [data model](data-model.md) and
[public contract](contracts/errors-and-fetch.md). Small image batches attempt
canonical GET immediately. Request missing-key results alone trigger listing;
request auth/config/exhausted connection errors propagate. Body and local writes
are counted failures with atomic cleanup; existing retry budgets remain. Memory
is limited to active workers and per-object/chunk data, never all batch bodies.

`FetchContext` adds optional complete inventory IDs; filtered/ID-only selections
never pretend to be complete. Full fetch uses that snapshot to prune. Promotion
still joins before a fresh inventory. `.tasks` is only touched for `save_tasks`.
Path lexical validation stays per record; filesystem confinement/resolution is
memoized by destination for that pass.

Diagnostics include operation, method, sanitized endpoint, resource IDs, UTC,
status, allowlisted request IDs and bounded safe summary. Per-pool request wrappers
pass a copied effective Retry with only `raise_on_status=False`; no temporary
shared-pool edits. Cover constructor bootstrap and already-used injected clients.
Per-request/operation context is reset in finally blocks. Retry logs label cveta2
attempt/budget and wait, not total HTTP attempts. Optional issues remain optional.

## Workstreams and Dependencies

1. Parent owns spec/plan/contracts/checklists/tasks/analyze and architecture plan gate.
2. After that gate, diagnostics agent owns CVAT/domain/facade/retry implementation
   and tests; application agent owns fetch context/orchestration/path enrichment and
   tests. Parent owns S3 transfer implementation/tests and benchmark harness.
3. Integrate; reconcile Russian guides, baseline, architecture and portable skill.
4. Parent runs required checks, benchmarks and serial live integration; fresh
   read-only agent reviews final integrated diff and Python/architecture evidence.
5. Resolve findings, converge, architecture acceptance, exact-path commits, merge
   to main and semantic-release Git-only tag/push; verify refs. No deployment/assets.

## Verification and Documentation

Focused tests cover image downloader/S3/files, fetch/cache/order/promotion and
CVAT requests/retries/issues/concurrency. Controlled local HTTP tests exercise
500/502/503/504/429, bootstrap, pagination, comments, exhausted SDK retries,
redaction and stale-context cleanup. Deterministic effect counts are primary
performance evidence; identical-worker cold/warm/fallback/large-image/annotation-heavy
benchmarks provide measured latency without universal claims.

Run `uv run lint-imports`, `uv run python scripts/check_architecture.py`,
`uv run pytest tests/test_architecture.py tests/test_docs.py`, full Ruff/mypy/Vulture,
full pytest with coverage, fast/full mutation profiles, uv build/lock check and
serial live integration using owned lifecycle tags. Required unavailable gates
remain gaps. Hook runs may supply these checks without redundant duplication.

Update README.md and docs/{cli,configuration,images-and-cache,python-api}.md in
Russian, baseline and architecture in English. Inspected companion source
`corp-skills/skills/cveta2/{SKILL.md,references/usage.md,references/evaluation.md}`
needs failure, diagnostics, `.tasks` and timing guidance/evaluation changes.
Validate under that repository's MAINTENANCE.md and release policy; record source
commit/checks in dated evidence. Do not install copies as a side effect.

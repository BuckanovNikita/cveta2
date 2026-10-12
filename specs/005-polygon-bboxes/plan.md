# Implementation Plan: Polygon bounding boxes

**Branch**: `feat/polygon-bboxes` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

## Summary

Convert standalone polygons in the shared extractor to min/max vertex bounds,
validate malformed inputs with contextual warnings and a skipped-count summary,
and invalidate caches containing previously omitted polygons. Preserve the
existing metadata mapping, rectangle branch, fetch flows and public interfaces.

## Technical Context

**Language/Version**: Python 3.10+; existing uv toolchain.

**Primary Dependencies**: Existing Pydantic, loguru, CVAT SDK; no additions.

**Storage**: Local and S3 task cache, CSV output; schema version 4 becomes 5.

**Testing**: pytest/FakeCvatApi/FakeS3Client, Ruff, mypy, import-linter, mutation
and configured commit/push hooks.

**Target Platform**: Existing supported Python CLI/API environments.

**Project Type**: CLI and library.

**Performance Goals**: Linear coordinate scans per polygon; no new network calls
except the required one-time cache refresh.

**Constraints**: No rounding/clipping, zero polygon rotation, no API/CLI/CSV or
dependency changes; no future-annotations imports in new code.

**Scale/Scope**: Standalone task shapes only; no tracks or segmentation output.

## Constitution Check

| Principle | Before research | After design |
| --- | --- | --- |
| Specify behavior first | Pass: approved spec and clarified intent | Pass: tasks precede code |
| Preserve architecture/compatibility | Pass: shared extractor owns geometry | Pass: no layer/interface changes; deletion tests |
| Types and failures | Pass: typed DTO input | Pass: finite checks, contextual diagnostics, skip summary |
| Verification | Pass: baseline failure reproduced | Pass: geometry, fetch, cache, conversion, gates and review planned |
| Ownership/docs/release | Pass: isolated branch; unrelated work preserved | Pass: scoped docs, commit, merge, semantic-release/tag-only push |

No exceptions or unresolved research questions.

## Project Structure

- `cveta2/_client/extractors.py`: polygon bounds, validation and warnings.
- `cveta2/_client/sdk_adapter.py`: accurate standalone-shape support warning.
- `cveta2/task_cache.py`: schema 5 invalidation.
- `tests/test_extractors.py`, `tests/test_sdk_adapter_conversion.py`: geometry,
  metadata, invalid input and adapter regressions.
- `tests/test_polygon_fetch.py`: both fetch services/CSV and deletion precedence.
- `pyproject.toml`: exact equivalent-mutant justifications for diagnostic-only
  capitalization/decoration; mutation scope and profiles remain unchanged.
- `tests/test_task_cache.py`, `tests/test_polygon_cache.py`: old local/S3 rejection
  and refreshed polygon payloads through real fetch orchestration.
- `README.md`, `docs/cli.md`, `docs/images-and-cache.md`,
  `.specify/memory/architecture.md`, and the living dataset contract: new behavior.
- This feature directory: spec, plan, research, data-model, contracts, quickstart,
  quality checklists, tasks and dated evidence.

## Implementation and dependencies

After requirements-quality review and cross-artifact analysis, extraction plus
adapter tests and cache version/regressions can proceed in independent workstreams
with disjoint file ownership. The parent owns fetch regressions and documentation.
Cache end-to-end tests depend on integrated extraction for their final green run.
Do not change partitioning, DTOs, API signatures or public columns.

Start with failing behavioral regressions, implement the minimal branches, then
run affected tests (extractor, SDK, client fetch, fetch services/task, cache,
conversion and docs). Parent reviews the accumulated diff and runs Ruff, mypy,
architecture checks and the configured commit gates including coverage and fast
mutation. Obtain fresh independent review, resolve findings and converge. Commit
only scoped files, merge to main, run semantic-release locally without VCS release,
and push main plus its generated tag through the full pre-push gates. Record live
integration execution or its configured absence honestly.

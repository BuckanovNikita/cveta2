# Implementation Plan: Storage and interfaces

**Branch**: `fix/review-bugs-20261004` | **Date**: 2026-10-04 | **Spec**: [spec.md](spec.md)

## Summary
Preserve architecture and successful calls; classify real boto3 wrappers, make cache invalidation best effort, preflight complete sync destination lists, validate file hits and config inputs, retain selected config identity, and correct command state and exit boundaries.

## Technical Context
Python 3.10+, existing boto3/botocore/Pydantic/Loguru and uv/pytest/Ruff/mypy/import-linter. Local files and S3 mocks; no live stand changes. Worker-count invariant accounting. Parent owns API, docs and mutation wrapper.

## Constitution Check
Pre-research: behavior specified, compatibility explicit, bounded ownership, typed catches, Russian diagnostics, regression-first tests, documentation assigned to parent. Post-design: same gates pass; no SDK imports beyond _client and no prompts in services/API. No tooling/dependency updates.

## Project Structure
Owned storage: image_uploader.py, image_downloader.py, s3_utils.py, task_cache.py. Interfaces: config.py, cli.py, commands/{doctor,ignore,setup_clearml}.py, commands/interactive/credentials.py; existing focused tests plus test_review_storage.py and test_review_interfaces.py. Parent implements API ignore removal and OPS-003 wrapper validation, updates docs and runs final gates/review.

## Verification
Write failing focused regressions before fixes. Run uv run --no-sync pytest on owned affected tests; Ruff and focused mypy; parent full pytest, import-linter, docs validation and independent review. Reproduce actual upload wrapper and non-root readonly failure; subprocess config/doctor exit checks. Record per-ID evidence and limitations.

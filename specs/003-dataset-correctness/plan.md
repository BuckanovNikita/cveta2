# Implementation Plan: Dataset correctness

**Branch**: `fix/review-bugs-20261004` | **Date**: 2026-10-04 | **Spec**: [spec.md](spec.md)

## Summary
Preserve CSV identities, validate export inputs before writes, refresh images, derive COCO ownership from prior annotation metadata, validate external YAML/YOLO values and preserve helper task/class correspondence.

## Technical Context
Python 3.10+, pandas, PyYAML, Pillow, Pydantic, Loguru. Local CSV/YAML/JSON and images; mocked existing SDK helper boundaries. Existing pytest, Ruff, mypy and import-linter toolchain. No dependency changes or live stand operations.

## Constitution Check
Before research: specification precedes changes; architecture and compatibility maintained; specific boundary exceptions; failing regressions and appropriate checks; parent owns documentation and final independent review. After design: same gates pass; existing helper SDK imports remain outside package layering and are not expanded.

## Project Structure
Owned modules: cveta2/services/convert/, cveta2/services/output.py, cveta2/services/merge.py, scripts/clone_project_to_s3.py, scripts/upload_dataset_to_cvat.py. Tests: existing affected suites and tests/test_review_dataset.py. Feature records remain in this directory.

## Verification
Run affected pytest suites, Ruff on changed owned Python, package mypy as appropriate. Parent runs docs/import/full checks and independent review. Record per-ID baseline and results in evidence.md. Parent documentation and integration gates remain unchecked until evidence exists.

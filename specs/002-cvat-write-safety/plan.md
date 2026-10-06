# Implementation Plan: CVAT write safety

## Summary

Resolve duplicate-name selection, validate incomplete boxes, bind recovery to complete normalized input and exact remote shape multisets, preserve completed state after cleanup failure, and prohibit ambiguous 503 replay.

## Technical Context

Python 3.10+, pandas, Pydantic, CVAT SDK through existing ports. Parent owns shared types/docs. No dependency updates, commits or live stand writes.

## Constitution Check

Before research: specified behavior and bounded ownership; no SDK imports outside `_client`; services prompt-free; Russian diagnostics; no future annotations introduced; regression-first and original-path evidence required.
After design: same checks pass. Existing ports already expose annotations/data metadata, so recovery can use TaskWriteSession without a new port. Shared documentation changes are requested from parent.

## Research and Design

Name resolution collects every scoped casefold match and rejects ambiguity. A shared validator in upload_manifest runs at service entry and direct annotation-write entry. Fingerprint normalizes every input row (excluding local-only path), preserves image order, and hashes behavior options. Schema bump rejects old recovery records. A completion marker is saved before unlink; completed stale recovery returns the recorded task outcome without replay. Recovery compares actual shapes against intended normalized shape multisets and validates ordered frame identity before writes, retaining available directories and allowing only exact cloud-prefix-relative names. Basename-only metadata falls back to unique basenames with a warning. Empty/deleted annotation inputs skip shape construction while still checking for conflicting remote shapes. 503 does not qualify as a proven refusal.

## Verification

Run focused regression tests on baseline before implementation, focused upload/read/retry tests after changes, Ruff and mypy for owned paths. Parent owns full suite, docs/import checks and independent review. Simulations establish client behavior only, not live incidence.

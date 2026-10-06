# Tasks: CVAT write safety

- [x] T001 Capture baseline observations and failing regression tests for CVAT-001..005.
- [x] T002 [US1] Reject duplicate project/task names in read.py and fetch.py; test numeric/scoped compatibility.
- [x] T003 [US2] Validate incomplete labelled boxes at service/write boundaries; test empty/deleted inputs.
- [x] T004 [US3] Version complete normalized fingerprint and persisted completion state in upload_manifest.py.
- [x] T005 [US3] Verify exact remote shapes and ordered frames before resume writes in upload.py/session.py.
- [x] T006 [US4] Stop 503 create/append replay and report uncertainty in sdk_adapter.py.
- [x] T007 Run owned focused tests, lint/type checks and record dated evidence/convergence.
- [x] T008 Parent: update shared Russian docs and validate docs/imports/full regression.
- [x] T009 Parent: fresh independent read-only review and integration of all sibling features.

## Convergence follow-ups

- [x] T010 Fix and verify columnless empty/deletion-only recovery; retain remote conflict checks for zero intended shapes.
- [x] T011 Compare available full/nested frame paths and cloud-prefix-relative names; reject changed directories before staging and ambiguous basename-only metadata.
- [x] T012 Correct obsolete empty-task recovery docstring and refresh focused/lint/type evidence.

## Parent static review follow-ups

- [x] T013 Fail closed on required recovery checkpoints before task create/data attach; regression-test denied pending/task-ID saves. Keep completion bookkeeping warnings and read-back fallback.
- [x] T014 Revalidate name selection against the authoritative scoped project list for an active client; preserve disconnected cached-only queries and numeric-ID handling. Regression-test stale single-match cache masking current duplicate names.

- [x] T015 Clear the deleted task identity before durably recording replacement creation pending; test applied-then-503 replacement refusal on subsequent resume.
- [x] T016 Strengthen semantic mutation regressions for normalized intent, frame order/path identity, exact shapes, completed cleanup and fresh-state guards; record read-only equivalent proofs separately for parent review.

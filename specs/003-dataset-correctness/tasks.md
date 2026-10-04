# Tasks: Dataset correctness

## Setup and foundations
- [x] T001 Inspect owned code, contracts, historical observations and feature prerequisites in specs/003-dataset-correctness/research.md.
- [x] T002 Record baseline reproduction per ID in specs/003-dataset-correctness/evidence.md.

## User Story 1
- [x] T003 [US1] Add DATA-001/002/003/004 regressions in tests/test_review_dataset.py.
- [x] T004 [US1] Correct deletion reading in cveta2/services/merge.py and export validation/refresh in cveta2/services/convert/common.py.
- [x] T005 [US1] Implement confined metadata-owned cleanup in cveta2/services/convert/coco.py.

## User Story 2
- [x] T006 [US2] Add DATA-005/006/007 regressions in tests/test_review_dataset.py.
- [x] T007 [US2] Correct expected CSV errors in cveta2/services/output.py and YAML/YOLO boundaries in cveta2/services/convert/yolo.py.

## User Story 3
- [x] T008 [US3] Add OPS-001/002 helper regressions in tests/test_review_dataset.py.
- [x] T009 [US3] Correct task frame correspondence in scripts/clone_project_to_s3.py and source class mapping in scripts/upload_dataset_to_cvat.py.

## Completion
- [x] T010 Run affected checks and reconcile convergence in specs/003-dataset-correctness/evidence.md.
- [x] T011 Parent documentation validation and independent review: specs/001-project-documentation/contracts/dataset-format.md and user documentation.

## Dependencies and strategy
T001 then T002; each story tests precede implementation; T010 follows all stories. Independent stories can run in parallel only with separate ownership. Deliver identity/input boundaries, then owned replacement, then helpers. Parent gates remain open until final evidence.

## Mutation verification follow-up
- [x] T012 Add boundary, ownership, contextual error and bounded EOF regressions for actionable mutation findings in tests/test_review_dataset.py; record targeted checks in specs/003-dataset-correctness/evidence.md.

T012 strengthens acceptance evidence; parent mutation rerun and review remain part of T011.

# Tasks: Dataset verification and reviewed publication

## Setup and foundation

- [x] T001 Inspect current/source repositories and preserve ownership in specs/008-dataset-verification-publication/research.md.
- [x] T002 Record agreed specification, clarification, design and architecture in specs/008-dataset-verification-publication/.
- [x] T003 Complete reviewer checklist and cross-artifact analysis in specs/008-dataset-verification-publication/checklists/publication.md and evidence/analysis-2026-10-20.md.
- [x] T004 Update validation/optional ClearML dependencies and exhaustive adapter contract in pyproject.toml and uv.lock.

## US1: Inspect and explicitly clean CSVs

Independent acceptance: both profiles preserve literal values and original row positions; cleanup is explicit and input never overwritten.

- [x] T005 [P] [US1] Port policy regression tests into tests/verification/ before implementing policy changes.
- [x] T006 [US1] Implement pure schemas, geometry, quarantine and inspection records in cveta2/domain/verification/.
- [x] T007 [US1] Implement strict CSV/report/media adapters and verification port/use case in cveta2/adapters/files/verification.py, media.py, cveta2/application/ports/verification.py and use_cases/verify.py.
- [x] T008 [US1] Wire verify CLI and prompt-free APIs through cveta2/composition/verification.py and cveta2/interfaces/.

## US2: Prepare a reviewable bundle

Independent acceptance: actual fixture images and fake remote ports produce a new bound bundle or a typed actionable failure.

- [x] T009 [P] [US2] Port class/task/path/bundle regression tests into tests/bundle/.
- [x] T010 [US2] Implement pure class reconciliation, task supersession and trainability policy in cveta2/domain/bundle/.
- [x] T011 [P] [US2] Implement HTTP classes and root adapters in cveta2/adapters/class_api/ and cveta2/adapters/files/bundle_paths.py.
- [x] T012 [US2] Implement four source snapshots, strict YAML, immutable preparation record and safe new-directory writes in cveta2/adapters/files/bundle.py.
- [x] T013 [US2] Implement structured decisions and prepare workflow through cveta2/application/ports/dataset_bundle.py, use_cases/dataset_bundle.py and composition/dataset_bundle.py.
- [x] T014 [US2] Wire bundle CLI options and prepare_dataset API in cveta2/interfaces/ with tests/bundle/ interface coverage.

## US3: Publish reviewed bundles later

Independent acceptance: unchanged snapshot finalizes exactly three files; every tested changed input/prerequisite blocks before child creation.

- [x] T015 [US3] Implement latest exact parent and exact payload finalization in cveta2/adapters/clearml/ with SDK failure/known-ID tests in tests/bundle/.
- [x] T016 [US3] Implement stable staged snapshot/full revalidation before publication in cveta2/application/use_cases/dataset_bundle.py and cveta2/adapters/files/bundle.py.
- [x] T017 [US3] Add source/payload tampering, newer-parent, class drift, missing-media/root and no-silent-cleanup regressions in tests/bundle/.
- [x] T018 [US3] Wire upload-dataset CLI and upload_dataset API with exit and prompt-free tests in cveta2/interfaces/ and tests/bundle/.

## US4: Remove automatic publication

Independent acceptance: fetch cannot construct a publisher; removed controls reject; CVAT upload regressions still pass.

- [x] T019 [P] [US4] Remove legacy fetch publisher, setup command and settings across cveta2/application/, adapters/config/, composition/ and interfaces/.
- [x] T020 [US4] Migrate existing affected fetch/config/API tests and replace legacy publication tests under tests/.

## Integration, documentation and release

- [x] T021 Extend affected negative architecture tests in tests/test_architecture.py and run declared import/effect gates.
- [x] T022 Update Russian README.md and docs/, architecture memory and specs/001-project-documentation/contracts/dataset-format.md.
- [x] T023 Update canonical corp-skills/skills/cveta2 package and evaluations; record companion source/checks in specs/008-dataset-verification-publication/evidence/.
- [x] T024 Add/run owned live publication and existing integration scenarios in tests/integration/; prove exact-tag cleanup.
- [x] T025 Run quality, full local regression, coverage, docs and package checks; record dated evidence in specs/008-dataset-verification-publication/evidence/.
- [x] T026 Obtain fresh independent final review, resolve findings and reconcile architecture.json with the complete diff.
- [x] T027 Run architecture acceptance and Spec Kit convergence; append any remaining work to this tasks.md.
- [ ] T028 Complete authorized task-owned commit, main merge, semantic-release evaluation and Git-only tag/commit pushes; record delivery evidence.

## Dependencies and parallel execution

T001–T003 precede implementation. T004 supports all new tests. Validator T005–T007,
bundle policy/remote T009–T011/T015, and legacy retirement T019–T020 can run with
exclusive ownership after the shared inspection contract is fixed. Parent owns
T012–T014/T016–T018 and waits for legacy interface edits before wiring. US3 depends
on valid US2 preparation; US2 consumes US1 policy. Documentation follows final
interfaces. Parent verification precedes fresh review; acceptance/convergence
precede release. No worker delegates further or commits independently.

## Phase 1: Convergence

- [ ] T029 Finish and record tool and companion Git-only delivery, replace unreleased portable guidance with the actual tool version, and reconcile T028 evidence per FR-017/SC-005 (partial). Runtime implementation, policy and architecture acceptance have no remaining gaps.

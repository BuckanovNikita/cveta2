# Tasks: Managed datasets

## Phase 1: Specification and planning
- [x] T001 Record approved requirements and clarification outcomes in spec.md (FR-001–020).
- [x] T002 Produce plan.md, research.md, data-model.md, contracts/managed.md and requirements-quality checklists.
- [x] T003 Validate architecture.json planning and cross-artifact analyze; resolve blockers before coding.

## Phase 2: Foundation
- [x] T004 Freeze neutral models in cveta2/domain/managed/models.py and focused schema tests (FR-001,006,016).

## Phase 3: US1 shared configuration — Wave 1 A
- [x] T005 [P] [US1] Implement configuration loading/ownership/migration in cveta2/adapters/config/project.py and migrate all readers/writers in settings.py; tests/test_managed_config.py (FR-001–005).
- [x] T006 [US1] Extend cveta2/interfaces/commands/setup.py and setup parser integration with attach/migration preview approval (FR-003–005).

## Phase 4: US2 sources — Wave 1 B
- [x] T007 [P] [US2] Implement typed source ports, source snapshot/reuse and CVAT/S3 effect adapters; tests/test_managed_sources.py (FR-006–010).

## Phase 5: US3 policies — Wave 1 C
- [x] T008 [P] [US3] Implement cveta2/domain/managed/policies.py splits/overlap/diff with tests/test_managed_policies.py (FR-011–014).
- [x] T009 Inspect and integrate Wave 1; run focused checks and reconcile contracts before dependent tasks.

## Phase 6: US3 preparation and US4 feedback — Wave 2
- [x] T010 [P] [US3] Implement managed snapshot/preparation persistence and validation with tests/test_managed_preparation.py (FR-011–014,016–018).
- [x] T011 [P] [US4] Implement typed CVAT feedback/idempotency and tests/test_managed_feedback.py (FR-015).
- [x] T012 [US4] Parent implements production composition, publication and CLI/API wiring; tests/test_managed_workflow.py (FR-016–019).
- [x] T013 [P] Update Russian docs, baseline, architecture context and external corp-skills cveta2 skill/references/evaluations; package validation and companion evidence (FR-020).

## Phase 7: Verification and acceptance
- [x] T014 Run focused and full regression, type/lint/build/docs/architecture checks and applicable mutation gates; dated evidence.
- [x] T015 Add/run mixed-source live CVAT/MinIO/ClearML scenarios using owned tag, serial lifecycle and exact cleanup; dated evidence.
- [x] T016 Obtain fresh independent final review after parent verification, fix findings, rerun affected checks.
- [x] T017 Run speckit-converge, append gaps without rewriting completed history, implement until no required work remains.
- [x] T018 Reconcile final owned diff/checks/docs/review in architecture.json and validate acceptance.
- [x] T019 Commit through project skill/hooks, merge-only main, semantic-release Git tag, authorized push verification; no GitHub Release/assets.

## Dependencies and ownership
T003 blocks T004; T004 blocks T005/T007/T008. T006 follows T005. T009 joins Wave 1. T010/T011/T013 run independently after T009 with exact exclusive file lists; parent T012 owns shared models/ports, composition, CLI registry, common fixtures and artifacts. T014–T019 are acceptance/release gates. Parent plus at most three children; bounded children never delegate, preserve other changes and return path/check evidence. Parent inspects every result. Read-only final reviewer has fresh context and no write ownership.

## Execution amendment — 2026-11-02

T010 preparation is assigned to policy agent C after T008 and parent inspection: it depends on frozen models/policies, not configuration/source implementation. T009 remains the final Wave1 integration barrier. A retains config regression migration updates; B retains source adapters before feedback. This avoids idle capacity without overlapping write ownership.

## Phase 8: Accepted cold-start follow-up

- [x] T020 [US2] Assert absent parent and no premature publication in tests/test_managed_workflow.py and live first-version publication/reuse in tests/integration/test_managed_dataset.py (FR-021, SC-007). Required before T019 release.

## Phase 9: Review and mutation remediation

- [x] T021 [US1] Preserve/flag colliding migration keys, validate final attach bytes before write, normalize supported legacy ignored-task IDs; regression tests/test_managed_migration_regressions.py and fresh independent review.
- [x] T022 [US1] Strengthen assertions for surviving settings.py mutations in tests/test_managed_mutation_policy.py and tests/test_managed_mutation_settings.py; inspect exact equivalents and rerun full gate without weakening scope.
- [x] T023 Run original three live upload paths again after CVAT auth429 throttling, then complete lifecycle cleanup and record initial35pass/3transient failures separately.

## Phase 10: Final live feedback acceptance

- [x] T024 [US4] Exercise actual mapped CVAT review issue creation/marker/deduplication, excluded-image clean publication and unchanged-task reuse under a new owned run; restore job states and prove exact-tag cleanup. Required before T019.

## Phase 11: Release acceptance identity regression

- [x] T025 [US1] Normalize empty organization to the personal workspace in shared identity and resolved CVAT settings; reproduce credential-save refusal for an otherwise valid shared organization empty string, verify YAML/environment aliases and unchanged shared bytes, rerun scoped/full checks and fresh independent review before publication. The initial v0.13.0 tag is local only; preserve immutable tags and release a patch after correction.

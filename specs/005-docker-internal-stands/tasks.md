# Tasks: HTTPS docker.internal integration stands

**Input**: [spec.md](spec.md), [plan.md](plan.md), [architecture.json](architecture.json)

**Process note**: T002–T008 were implemented, reviewed and tested before this ledger existed; they are marked complete from the inspected diff and the checks in [verification evidence](evidence/verification-2026-11-03.md). T009 onwards were performed in the artifact pass.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Specification and planning

- [x] T001 Record spec.md, checklists/requirements.md, plan.md and architecture.json; validate the architecture record with `--phase plan` (exit 0, after implementation — see process note).

## Phase 2: User Story 1 - Live runs reach the HTTPS stands (P1)

- [x] T002 [US1] Document the helper CA variables and HTTPS names in scripts/integration_env.sh; evaluate the helper env output unchanged (FR-002).
- [x] T003 [P] [US1] Switch defaults to https://cvat.k8s.docker.internal in tests/integration/conftest.py and tests/integration/test_e2e.py (FR-001).
- [x] T004 [P] [US1] Update offline fixtures to HTTPS names and CA exports in tests/test_integration_env.py, tests/test_seed_cvat.py, tests/test_cvat_stand.py, tests/test_clearml_run.py; assert CA variables reach child processes (FR-001, FR-002, SC-001).

## Phase 3: User Story 2 - Trust failures are reported as TLS problems (P1)

- [x] T005 [US2] Add tests/integration/stand_tls.py (find_tls_error, tls_failure_message, StandTlsError) and tests/test_stand_tls.py (FR-004, FR-008).
- [x] T006 [US2] Classify TLS failures in tests/integration/cvat_stand.py, tests/integration/seed_cvat.py (CVAT login and MinIO seeding) and the live SDK fixture in tests/integration/conftest.py; re-raise non-TLS errors unchanged (FR-004, FR-005). Depends on T005.
- [x] T007 [US2] Add integration_curl_tls_failure and INTEGRATION_TLS_REMEDY in scripts/integration_env.sh; use them in scripts/integration_gate.sh and scripts/integration_test.sh; offline gate tests for curl exit 60 vs 7 and the ClearML trust hint (FR-003, FR-005, FR-006, SC-002).

## Phase 4: Documentation

- [x] T008 [P] Describe HTTPS names, CA variables and TLS troubleshooting in CONTRIBUTING.md (Russian) and .claude/skills/running-integration-tests/SKILL.md (FR-007). Inspected no-change: specs/baseline.md, docs/, README.md, .specify/memory/architecture.md, corp-skills skills/cveta2 at 670b0be.

## Phase 5: Architecture and verification

- [x] T009 Add scoped boundary contract tests/test_integration_tool_boundaries.py: stand_tls.py imports only ssl; runtime cveta2 imports no tests/scripts tooling; negative fixtures for forbidden imports (FR-008). Added in the artifact pass because no existing contract covered tooling outside the cveta2 root package.
- [x] T010 Run ruff format --check, ruff check, mypy, lint-imports, check_architecture.py, vulture, focused suites, boundary tests, docs tests and full non-integration pytest; record dated results (SC-003). Depends on T002–T009.
- [x] T011 Cross-artifact analysis (evidence/analysis.md); clarify and converge: no open questions, no remaining in-scope work besides T013–T014.
- [x] T012 Reconcile the task-owned diff, checks and review in architecture.json; validate with `--phase acceptance`. Depends on T010.
- [x] T013 Live run of the integration lifecycle against the HTTPS stands with one owned run tag and exact-tag cleanup, via the running-integration-tests skill (SC-004). Done 2026-11-03 under tag cveta2-claude-20261103-https-move-fl1u: 38 passed, 0 skipped; exact-tag cleanup proven (evidence/integration-2026-11-03.md).
- [x] T014 Fresh independent read-only review of the final diff including these artifacts and T009; the launching agent reported a prior review of the implementation only. Done 2026-11-03: separate-subagent static review, verdict ACCEPT (evidence/review-2026-11-03.md).
- [ ] T015 After merge to main: semantic-release evaluation and Git-tag-only release per CONTRIBUTING.md (owner's merge-only workflow; not performed here).

## Dependencies

T005 blocks T006. T002–T009 block T010; T010 blocks T012. T013 (live run) and T014 (independent review) were completed on 2026-11-03; T015 remains an open release item outside this change's authorization. Single agent; no parallel delegation was used in the artifact pass.

## Phase 6: Authorized release resumption — 2026-11-03

The user now authorizes T015 and the final push after checks and independent review.
The earlier authorization limit above describes the original artifact pass.

- [x] T016 Reconcile stale live-run statements and the instruction-migration receipt/ledger, verify the integrated candidate, validate architecture acceptance and obtain fresh independent final review before T015 delivery (Constitution II, IV, V; plan: release resumption). Preserve prior evidence and unrelated work. Final reviewer returned ship; see evidence/release-2026-11-03.md.

## Phase 7: Candidate reconciliation — 2026-11-04

- [ ] T017 Reconcile the staged tree with preserved commit `6252649`, run fresh scoped checks and architecture acceptance, obtain independent review, and deliver T015 through native gates. Record actual results in evidence/release-2026-11-03.md. Prior dated outcomes remain historical, candidate-specific evidence.

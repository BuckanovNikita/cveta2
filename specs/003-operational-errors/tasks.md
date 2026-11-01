# Tasks: Operational errors

## Phase 1: Setup and foundation

- [x] T001 Inspect original YAML and decorated retry failures; record safe boundary decisions in research.md.
- [x] T002 Review checklists/quality.md and validate architecture.json before implementation.

## Phase 2: US1 - Safe configuration diagnostics

- [x] T003 [US1] Add failing sentinel/source-position/API/CLI cases in tests/test_review_interfaces.py (FR-001, FR-002).
- [x] T004 [US1] Sanitize malformed-YAML diagnostics at cveta2/adapters/config/settings.py while retaining cause and valid configuration behavior.
- [x] T005 [US1] Verify config/interface suites and original CLI path; record results in evidence/verification-2026-11-01.md.

## Phase 3: US2 - Invalid retry delay fallback

- [x] T006 [US2] Reproduce invalid negative/nonfinite Retry-After through the decorated read in tests/test_retry_policy.py; retain zero/positive and write-safety coverage (FR-003, FR-004).
- [x] T007 [US2] Validate delay values at cveta2/adapters/cvat/transport.py; verify real attempt budget and final typed error.

## Phase 4: Acceptance and delivery

- [x] T008 Reconcile specs/baseline.md, docs/configuration.md and dated evidence; document portable-skill no-change reason.
- [x] T009 Run integrated architecture/static/coverage and fast/full mutation plus configured live gates; fresh final review and architecture.json acceptance.
- [x] T010 Converge spec.md, plan.md and tasks.md; authorized main merge, release evaluation and Git commit/tag delivery.

## Dependencies and implementation strategy

T001 -> T002 -> T003 -> T004 -> T005; US2 may proceed after T002 but one
implementer owns this bounded stream and performs T006 -> T007 sequentially.
T008 follows both stories, T009 follows integration, T010 follows acceptance.
Other streams have disjoint runtime/test ownership; parent owns shared docs.

## Phase 5: Convergence

- [x] T011 Complete the required live integration evidence and Git delivery in T009/T010 after the external stand prerequisite is restored; retain results in evidence/verification-2026-11-01.md (plan: Acceptance and Documentation; partial).

# Tasks: Nullable completion

## Phase 1: Setup and foundation

- [x] T001 Inspect completion policy, baseline and original dtype-dependent failure; record design in research.md.
- [x] T002 Review checklists/quality.md and validate architecture.json before implementation.

## Phase 2: US1 - Unknown completion evidence

- [x] T003 [US1] Reproduce nullable stage/state and boolean completion failures in tests/test_partition.py; cover explicit overrides (FR-001, FR-002).
- [x] T004 [US1] Normalize completion evidence at cveta2/domain/partition.py without changing consumers or schema (FR-001–FR-003).
- [x] T005 [US1] Run tests/test_partition.py and tests/test_whats_new.py for shared membership, deletion/recency and unchanged API behavior (FR-003).

## Phase 3: Acceptance and delivery

- [x] T006 Update specs/baseline.md and dated evidence/verification-2026-11-01.md; document portable-skill no-change reason.
- [x] T007 Run integrated architecture/static/coverage and fast/full mutation plus configured live gates; obtain fresh final review and validate architecture.json acceptance.
- [x] T008 Converge spec.md, plan.md and tasks.md; complete authorized main merge, release evaluation and Git commit/tag delivery.

## Dependencies and implementation strategy

T001 -> T002 -> T003 -> T004 -> T005 -> T006 -> T007 -> T008.
The US1 fix is the smallest complete increment. This stream may run in parallel
with operational-errors and maintenance after their planning gates; it owns only
cveta2/domain/partition.py and tests/test_partition.py. Parent owns shared artifacts.

## Phase 4: Convergence

- [x] T009 Complete the required live integration evidence and Git delivery in T007/T008 after the external stand prerequisite is restored; retain results in evidence/verification-2026-11-01.md (plan: Acceptance and Documentation; partial).

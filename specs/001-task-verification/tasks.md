# Tasks: Development verification

Input: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md).
Manual tooling experiments are evidence, not a new repository test suite.

## Phase 1: Setup

- [x] T001 Select specs/001-task-verification and prepare spec, clarification scan, plan, quality checklists and analysis.
- [x] T002 Amend .specify/memory/constitution.md for the user-approved verification and deferral policy.

## Phase 2: Foundational evidence

- [x] T003 Record disposable selection, invalidation, failure, interruption, Task exit-code and staging-shim experiments in docs/plans/task-verification-20261109/feasibility.md before production hook changes (FR-001, FR-002, FR-004, FR-011).

## Phase 3: US1 — Verify once

Independent check: initial/repeated units and relevant changed inputs receive observed coverage.

- [x] T004 [US1] Add go-task-bin to pyproject.toml and resolve uv.lock.
- [x] T005 [US1] Define explicit fixes, checks, test/test-full, unique temporary build, verify, properties and mutation in Taskfile.yml (FR-001–FR-003, FR-011, FR-012).
- [x] T006 [US1] Define inline conservative testmon namespace and worker controls in Taskfile.yml; validate Python, configuration, static-asset and path changes against dated evidence (FR-002).

## Phase 4: US3 — Infrastructure deferral

Independent check: read-only bounded preflight distinguishes 0/3/1 with no resources.

- [x] T007 [US3] Add bounded preflight and bounded Task-driven setup to tests/integration/lifecycle.py, preserving access/error classification and exact-tag cleanup (FR-006, FR-007, FR-012).
- [x] T008 [US3] Define infra-check, integration, clean-tip acceptance and explicit release-check in Taskfile.yml, including sequential ordering and exit preservation (FR-006–FR-009).

## Phase 5: US2 — Commit in isolated worktrees

Independent check: disposable current/legacy worktrees, input rejection and rollback.

- [x] T009 [US2] Add minimal dynamic-worktree staging shim and scripts/install-hooks.sh with prior-installation rollback; consolidate .pre-commit-config.yaml to serial always-selected verification and Conventional Commit validation (FR-004, FR-005).
- [x] T010 [US2] Exercise worktree environment/history/cache separation, partially staged and untracked rejection and legacy dispatch; record results in specs/001-task-verification/evidence.md (FR-004, FR-005).

## Phase 6: Guidance and integrated validation

- [x] T011 [P] Migrate AGENTS.md, .specify/memory/engineering.md, README.md, authored skills, new verification-workflow skill/symlink and docs/adr/task-verification.md; leave generated tools and glossary unchanged (FR-010).
- [x] T012 Run integrated development verification after all edits stop, inspect mechanical fixes separately and record actual counts/timings/outcomes in specs/001-task-verification/evidence.md (SC-001, SC-002).
- [ ] T013 Run properties, applicable mutation and live acceptance on the clean committed tip; leave this unchecked while any required verification is deferred (FR-007–FR-009, SC-003).
- [x] T014 Obtain fresh independent review after integration and verification, resolve findings and rerun affected checks; record in specs/001-task-verification/evidence.md (SC-004).
- [ ] T015 Converge implementation against spec, plan and tasks; keep deferred acceptance visibly incomplete in specs/001-task-verification/tasks.md and report passed/failed/deferred/cleanup outcomes (SC-003, SC-004).

## Dependencies and execution

T003 precedes production hook migration. T004–T006 precede T007–T008, which precede
T009–T010. Guidance drafting T011 may run independently with explicit file ownership.
T012 waits for all editing to stop; T013 and review T014 follow integrated checks.
Convergence T015 is last. US1 is the local-verification MVP, not acceptance of the
whole migration. No shared heavy-job lock or same-worktree editing during checks.

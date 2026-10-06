# Tasks: Project documentation in Spec Kit

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md)

## Phase 1: Foundation

- [x] T001 Capture scope, destinations, acceptance criteria, and reviewed quality checklists in specs/001-project-documentation/ (FR-008).

## Phase 2: Agent discovery (US1)

- [x] T002 Move portable rules to .specify/memory/engineering.md and architecture to .specify/memory/architecture.md; replace AGENTS.md with discovery guidance and preserve CLAUDE.md (FR-001, FR-002).
- [x] T003 Update .specify/memory/constitution.md for canonical ownership and living shared references (FR-001, FR-002, FR-007).

## Phase 3: Contracts and evidence (US2)

- [x] T004 Move DATASET_FORMAT.md to specs/001-project-documentation/contracts/dataset-format.md and BUG_REVIEW.md to specs/001-project-documentation/evidence/bug-review-2026-09-04.md without changing their content (FR-003, FR-004).
- [x] T005 Update human guide links, skill cross-references, cveta2/api.py documentation, and pyproject.toml source-package inclusion (FR-005, FR-007).

## Phase 4: Verification and convergence

- [x] T006 Extend tests/test_docs.py to cover migrated document links, language, discovery, and retired-source absence (FR-006).
- [x] T007 Run quickstart checks, verify source fidelity and package content, review scope, and record dated evidence in specs/001-project-documentation/evidence/verification-2026-09-30.md (FR-005–FR-008).
- [x] T008 Reconcile spec/plan/tasks with the final migration, mark only verified tasks complete, and record convergence in the dated evidence (FR-008).

## Dependencies and Implementation Strategy

T001 precedes implementation. T002 and T004 establish destinations before
T003/T005 update consumers. T006 precedes T007; T008 depends on passing checks.
US1 and US2 have separate source documents but share navigation and verification:
execute this small migration inline without parallel writers. A read-only
review can run independently after the destinations and consumers are updated.

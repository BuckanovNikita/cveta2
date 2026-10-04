# Tasks: Storage and interfaces

## Phase 1: Regressions

- [X] T001 Capture baseline and add storage regressions STOR-001..004, UI-001.
- [X] T002 Add interface regressions UI-002..007, including subprocess exits.

## Phase 2: Implementation

- [X] T003 Repair upload classification, cache invalidation, complete sync preflight, and file-only cache hits.
- [X] T004 Repair cache name containment, typed timeout/config boundaries, selected config source, ClearML toggle persistence and CLI ignore removal.
- [X] T005 Repair doctor required/optional/disabled classification and exits.
- [x] T006 Parent: repair API stale ignore removal and OPS-003 unknown mutation profile handling.

## Phase 3: Verification and documentation

- [X] T007 Run focused checks and record per-ID evidence.
- [x] T008 Parent: update user docs and validate Markdown/examples/local links.
- [x] T009 Parent: full regression, import-linter, mutation gate if required, independent review.

Dependencies: T001/T002 precede T003..T005; T006 independent parent work; T007 follows implementation; parent gates remain unchecked until evidenced.

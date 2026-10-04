# Feature Specification: CVAT write safety

**Feature Branch**: `fix/review-bugs-20261004`
**Created**: 2026-10-04
**Status**: Implemented; parent gates pending
**Input**: Resolve CVAT-001 through CVAT-005.

## User Scenarios & Testing

### User Story 1 - Unambiguous selection (Priority: P1)

Operators need the intended project/task before mutation.
**Why this priority**: Wrong-target writes affect unrelated data.
**Independent Test**: Duplicate names reject regardless of ordering.
**Acceptance Scenarios**:

1. Given duplicate case-insensitive project/task names, selection fails with matching IDs before writes.
2. Given numeric IDs, existing ID and organization/project scope semantics remain available.

### User Story 2 - Complete annotation input (Priority: P1)

Operators need malformed boxes rejected before external writes.
**Why this priority**: Silent omission falsely reports success.
**Independent Test**: Every missing bbox coordinate rejects before S3/task creation.
**Acceptance Scenarios**:

1. Given a labelled box missing a coordinate, validation identifies row/image and prevents every external write.
2. Given valid empty or deleted records, validation accepts them.

### User Story 3 - Exact recovery (Priority: P1)

Interrupted uploads must continue only their recorded intent.
**Why this priority**: Changed intent can mix old boxes with new issues.
**Independent Test**: Edited input rejects; exact remote shape multisets reuse; conflicts stop.
**Acceptance Scenarios**:

1. Given changed annotations, labels, attributes, issues, deletions, frame order/mapping or behavior options, resume rejects before writes.
2. Given insufficient legacy state, resume rejects safely.
3. Given exact remote shapes, recovery reuses them; partial/conflicting nonempty sets stop without append.
4. Given remote completion followed by cleanup failure, success identifies the task and stale state; subsequent recovery cannot duplicate writes.

### User Story 4 - Ambiguous writes (Priority: P1)

Operators need uncertainty reported after potentially committed writes.
**Why this priority**: Replay creates duplicate tasks/shapes/issues.
**Independent Test**: Applied-then-503 fake records one effect.
**Acceptance Scenarios**:

1. Given create/append 503 with any Retry-After, there is no automatic replay.
2. Given transient reads or proven refused writes, justified retries remain.

### Edge Cases

Casefold collisions; zero shapes; duplicate boxes; reordered frames; interrupted attach; unknown task identity; remote edits; permission denied during cleanup.

## Requirements

### Functional Requirements

- **FR-001 / CVAT-001**: Reject ambiguous names with matching IDs before mutation; retain numeric IDs and scopes.
- **FR-002 / CVAT-002**: Reject incomplete labelled boxes before external writes; preserve empty/deleted records.
- **FR-003 / CVAT-003**: Version complete normalized intent identity including annotations, labels, attributes, issues, deletions, ordered frame intent and behavior-affecting options; reject changed and legacy insufficient intent before writes.
- **FR-004 / CVAT-003**: Reuse remote shapes only after exact semantic multiset verification; reject partial/conflicting nonempty sets without append.
- **FR-005 / CVAT-004**: Cleanup failure after remote success warns with task/stale state and prevents later duplicate writes.
- **FR-006 / CVAT-005**: Never replay ambiguous create/append 503 even with Retry-After; report uncertainty and support known-identity read-back recovery while retaining safe retries.

### Key Entities

Upload intent contains normalized rows, ordered images, deletions, labels and options. Recovery state contains version, fingerprint, frozen storage/frame mapping, known task ID and completion marker. Shape identity preserves duplicate multiplicity.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Five simulated failure paths receive regression assertions and dated boundary evidence.
- **SC-002**: Invalid or changed input results in zero external writes.
- **SC-003**: Ambiguous write simulation produces one remote effect.
- **SC-004**: Verified recovery creates zero duplicate shapes.

## Assumptions

No live stand failure was observed. Existing SDK seam and prompt-free service contracts remain. Unsupported row properties participate in identity to prevent content-blind recovery. Concurrent remote edits cause rejection. Available full or nested CVAT frame names must preserve directory identity, permitting only documented cloud-prefix omission. Basename-only metadata permits unique-name comparison with an explicit warning; repeated basenames reject because identity cannot be verified. Dataset work: [003-dataset-correctness](../003-dataset-correctness/spec.md). Storage work: [004-storage-interfaces](../004-storage-interfaces/spec.md).

## Clarifications

### Session 2026-10-04

No questions: user supplied hard rejection, exact reconciliation, conservative legacy handling, warning after completion and no ambiguous replay. Functional/data/failure/compatibility coverage is clear; live incidence remains outside scope.

### Follow-up clarification 2026-10-04

Parent explicitly confirmed that available nested/full metadata paths must be compared without discarding directories. Basename-only metadata may use unique basenames with a documented limitation. Empty and deletion-only recovery must work even when there are no annotation columns.

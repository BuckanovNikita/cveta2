# Feature Specification: Nullable completion evidence

**Feature Branch**: `cleanup/contracts-and-release`
**Created**: 2026-11-01
**Status**: Implemented; acceptance and release pending
**Input**: Full cleanup, preserving supported behavior; repair the completion bug
found during the audit. Delta from [baseline](../baseline.md#output-and-partition-rules).

## User Scenarios & Testing

### User Story 1 - Treat unknown completion as unfinished (Priority: P1)

API users supplying tables with nullable columns receive the same task membership
as users supplying ordinary object columns.

**Independent Test**: Partition identical rows using object and nullable string
columns; compare completed IDs and output membership.

**Acceptance Scenarios**:

1. **Given** a task with one finished row and one unknown stage/state, **when**
   completion is inferred, **then** all task annotations remain in progress.
2. **Given** explicit false completion, **when** its row stage/state is finished,
   **then** the task remains in progress.
3. **Given** explicit true completion, **when** row stage/state is missing,
   **then** existing explicit-completion precedence is preserved.

### Edge Cases

- Missing stage, missing state, both missing, nullable boolean completion and
  mixed tasks retain existing fallback, deletion and task-ID recency rules.
- Empty tables remain supported; no new columns or output formats are introduced.

## Requirements

### Functional Requirements

- **FR-001**: Unknown legacy row stage/state MUST count as unfinished evidence,
  independent of nullable versus ordinary column representation.
- **FR-002**: Explicit completion MUST retain the existing true/false precedence;
  missing explicit completion MUST use the legacy row fallback.
- **FR-003**: Partitioning and completed-task membership consumers MUST agree;
  deletion precedence and output ordering MUST remain unchanged.

### Key Entities

- **Completion evidence**: Optional explicit completion and legacy row stage/state.
- **Task membership**: Completed IDs shared by partitioning and baseline comparison.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every unknown-evidence regression gives identical task membership
  for the supported nullable and ordinary representations.
- **SC-002**: No unfinished task enters the completed dataset through missing
  legacy evidence; existing completion/partition acceptance cases remain valid.

## Assumptions

- User confirmed that supported commands, APIs and behavior must be preserved.
- This corrects an implementation violation of the baseline; it does not introduce
  a new definition of completion or broaden supported annotation shapes.

## Clarifications

### Session 2026-11-01

- Compatibility scope is resolved by the user's preservation choice. The baseline
  already defines unfinished evidence and explicit-completion precedence; there
  are no material unanswered product questions.

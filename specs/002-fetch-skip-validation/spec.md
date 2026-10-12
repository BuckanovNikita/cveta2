# Feature Specification: Fetch without validation

**Feature Branch**: `feat/fetch-skip-validation-integrated`
**Created**: 2026-10-12
**Status**: Accepted for implementation
**Input**: Implement the supplied fetch --skip-validation plan.

## User Scenarios & Testing

### User Story 1 - Accept finished annotation work before export (Priority: P1)

A project owner who does not require validation can accept finished annotation
work and export the resulting dataset in one fetch.

**Independent Test**: A project containing all-annotation-completed and mixed
annotation/acceptance-completed tasks exports their accepted rows.

**Acceptance Scenarios**:

1. Given at least one job and only annotation/completed or acceptance/completed
   jobs, enabling the option promotes each annotation/completed job in CVAT.
   Every exported row then reflects acceptance/completed and task completion.
2. Given completed-only selection, newly accepted tasks appear in the same run.
3. Given the option is omitted, no promotion reads or writes are introduced.

### User Story 2 - Preserve unfinished and ignored work (Priority: P1)

The owner can use the option without accepting tasks that still require work.

**Independent Test**: Empty, ignored, unfinished, rejected and validation-stage
cases receive no updates; a fully accepted task receives no redundant writes.

**Acceptance Scenarios**:

1. A single disallowed job makes its entire task ineligible, including Ground
   Truth, replica and jobs without exported frames.
2. Ignored tasks are not inspected for promotion, regardless of silent warnings.
3. Existing deletion precedence, task-id recency, ordering and CSV schemas remain.

### User Story 3 - Recover from partial promotion (Priority: P2)

The owner sees a useful failure and can rerun without undoing completed changes.

**Independent Test**: Fail a later job update, observe no annotation fetch or
output publication, then retry and update only the remaining eligible jobs.

**Acceptance Scenarios**:

1. A promotion read/write failure aborts before annotation fetching, downloads,
   CSV writes or ClearML publication, and identifies the task and job when known.
2. Successful CVAT changes persist. A retry rechecks jobs and avoids accepted jobs.
3. Cache entries for tasks with attempted mutations are invalidated even after
   partial failure, using the fetch configuration and enabled S3 mirror.

### Edge Cases

Zero jobs never qualifies. Any state other than completed, any stage other than
annotation or acceptance, and unknown values make the task ineligible. All jobs
count irrespective of type or frame coverage. With concurrent tasks, all workers
finish promotion before normal fetch; failures cannot publish partial outputs.

## Requirements

### Functional Requirements

- **FR-001**: Provide opt-in `fetch --skip-validation` and keyword-only
  `cveta2.fetch(..., skip_validation=False)`, including command echo. Leave
  `fetch-task` and `fetch_task` unchanged.
- **FR-002**: Inspect every non-ignored project task before applying completed-only.
  Qualify only nonempty job lists whose every pair is annotation/completed or
  acceptance/completed, without filtering job type or frame coverage.
- **FR-003**: Update only qualifying annotation/completed jobs to
  acceptance/completed in CVAT; fully accepted tasks need no writes.
- **FR-004**: Finish promotion before normal fetch retrieves fresh task metadata.
  Bound simultaneous tasks by configured CVAT workers; update each task sequentially.
- **FR-005**: Preserve all existing CSV partitioning, deletion precedence,
  task-id ordering, image paths, schema and default behavior.
- **FR-006**: Invalidate affected local cache entries and the enabled S3 mirror
  using the same configuration as fetch, including partial mutation failures.
  Cache-disabled runs must not contact the S3 cache.
- **FR-007**: Abort on promotion reads/writes failing before fetching annotations
  or publishing outputs. Identify task/job, preserve successful CVAT changes,
  and permit a retry without redundant updates.

### Key Entities

- Task: project membership, ignore status, full job list and fresh completion metadata.
- Job: id, stage, state, type and frame coverage; the last two do not limit eligibility.
- Cached task: annotation rows and completion state in configured local/S3 storage.

## Success Criteria

### Measurable Outcomes

- **SC-001**: All eligible tasks appear as accepted in CVAT and completed in the
  same export, including completed-only selection.
- **SC-002**: No excluded task or previously accepted job is changed.
- **SC-003**: A failed promotion produces no new export and retry completes only
  remaining eligible transitions; stale cache data never supplies promoted rows.
- **SC-004**: Default fetch and fetch-task retain their established behavior.

## Assumptions

Existing CVAT credentials authorize job updates; permission errors fail the run.
There is no cross-job transaction or rollback. External concurrent editors are
outside the atomicity guarantee; eligibility is based on the retrieved job list.
Promotion requires successful cache invalidation before the first job update;
an invalidation failure aborts without mutating that task. Ordinary fetch cache
transport errors retain their existing warning/fallback policy. No new configuration or dependency
is required. Git tags only; no GitHub Release or package publication.

## Clarification review

2026-10-12: The supplied plan resolves scope, eligibility, errors, defaults and
recovery. No material clarification is needed. Timing is a barrier guarantee,
not a new latency target. Existing S3-disable policy and ordinary fetch cache failure policy are preserved.

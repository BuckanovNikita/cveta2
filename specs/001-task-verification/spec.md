# Feature Specification: Development verification

**Feature Branch**: `chore/simplify-hooks-20261109`

**Created**: 2026-11-09

**Status**: Draft

**Input**: User-approved plan, “Migrate verification to Task without unsafe completion caching”.

This changes development verification and operational policy only. The product
behavior in [the baseline](../baseline.md), public interfaces and dataset contract
remain unchanged.

## User Scenarios & Testing

### User Story 1 - Verify a change once (Priority: P1)

A contributor runs explicit safe fixes, stages the complete change and verifies
it without duplicate stages or unnecessary execution of unaffected unit tests.

**Why this priority**: Reduce redundant work while preserving meaningful checks.

**Independent Test**: In a disposable checkout, observe initial, unchanged,
changed-input, failure and interrupted runs and their actual execution counts.

**Acceptance Scenarios**:

1. **Given** successful unit history, **when** unchanged inputs are checked again,
   **then** unaffected tests are omitted while required static commands still run.
2. **Given** changed Python behavior, **when** verification runs, **then** affected
   tests run; failed tests run again on the next attempt.
3. **Given** configuration, dependency, static asset or relative file membership
   changes, **when** units run, **then** conservative coverage uses a fresh baseline for an unseen input namespace;
   matching verified history may be reused when inputs revert.
4. **Given** an interrupted command, **when** a contributor reports completion,
   **then** that run cannot establish successful verification.

### User Story 2 - Commit in isolated worktrees (Priority: P2)

A contributor commits fully staged repository inputs with checks applying to the
invoking worktree, while older worktrees retain their previous workflow.

**Why this priority**: Prevent claims about staged content that was not verified.

**Independent Test**: Exercise staged, partially staged, untracked and ignored
inputs, and new and legacy worktree hook paths, in disposable repositories.

**Acceptance Scenarios**:

1. **Given** unstaged tracked or nonignored untracked inputs, **when** a commit
   starts, **then** it is rejected before the hook runner can hide inputs.
2. **Given** two worktrees, **when** their hooks run, **then** each uses its own
   configuration, environment and mutable verification data.
3. **Given** an older worktree, **when** shared hooks run, **then** its existing
   configuration remains usable and the prior hook installation is recoverable.

### User Story 3 - Defer unavailable live verification (Priority: P3)

A contributor receives a bounded infrastructure result and can continue local
work while live acceptance remains explicitly incomplete.

**Why this priority**: An unavailable stand must neither stall unrelated work nor
silently become a passed acceptance gate.

**Independent Test**: Observe bounded available, unavailable and erroneous
preflights, then exercise actual live acceptance and exact-tag cleanup when available.

**Acceptance Scenarios**:

1. **Given** a temporary outage or capacity wait, **when** preflight runs,
   **then** it reports UNAVAILABLE and exits 3 within the configured deadline.
2. **Given** missing prerequisites, credentials, trust or authorization,
   **when** preflight runs, **then** it reports ERROR and exits 1.
3. **Given** available services, **when** preflight runs, **then** it reports
   AVAILABLE and exits 0 without creating a run tag or service resources.
4. **Given** deferred live checks, **when** local work finishes, **then** acceptance,
   merge and release remain blocked pending successful live verification.

### Edge Cases

Failed setup with owned resources requires exact-tag cleanup and a leftovers
report. Loss of availability during setup is blocked setup; assertion failures
remain test failures. Interruptions provide no success evidence. Additions,
removals and moves use full relative paths. Explicit operator waits remain
available; default verification waits are bounded. No concurrent edits and
verification may run within one worktree.

## Requirements

### Functional Requirements

- **FR-001**: Each verification run MUST invoke each required command once,
  preserving failures and distinguishing execution from affected-test omission.
- **FR-002**: Unit selection MUST cover changed Python behavior and failed tests;
  untracked dependency inputs MUST conservatively invalidate the baseline.
- **FR-003**: Automatic safe fixes MUST be explicit and MUST NOT stage files.
- **FR-004**: Commits MUST reject unstaged tracked and nonignored untracked inputs
  before running verification; Conventional Commit validation MUST remain active.
- **FR-005**: Worktrees MUST isolate mutable environments, history and caches,
  preserve legacy hooks and retain a recoverable prior installation.
- **FR-006**: Read-only preflight MUST preserve outcomes 0/3/1 and use a configurable
  overall deadline defaulting to 60 seconds; live runs MUST recheck availability.
- **FR-007**: Deferred checks MUST be reported separately from failures, MUST block
  acceptance/merge/release, and MUST allow independent local work to continue.
- **FR-008**: Acceptance MUST require a clean tip, checks, packaging, randomized
  properties and full-suite coverage including live tests without a preceding
  duplicate affected-unit stage.
- **FR-009**: Release MUST retain fast-forward integration, shared locking,
  semantic-release ownership and separate push authorization. The documented
  version/changelog/lockfile exception MUST require an explicit release check.
- **FR-010**: Authored guidance and skills MUST expose one completion procedure;
  generated Spec Kit tools and the dataset glossary MUST remain unchanged.
- **FR-011**: Verification MUST use no persisted completion receipts or orchestration
  freshness to infer success. Mutation survivors remain advisory; tool errors
  remain unresolved. Property, mutation, preflight and live checks are never cached.
- **FR-012**: Packaging MUST clean only uniquely owned temporary output; shared
  services and unrelated resources MUST remain intact.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Dated experiments record commands, exit codes, selected tests and
  execution counts for every scenario in US1 and US2.
- **SC-002**: An unchanged unit repeat executes fewer tests than its initial run;
  every changed-input scenario receives the required coverage.
- **SC-003**: Availability outcomes and interruptions propagate without any false
  success claim, and unavailable live acceptance remains visibly incomplete.
- **SC-004**: Integrated verification and fresh independent review establish one
  discoverable procedure shared by both agent hosts.

## Assumptions

The supplied plan settles the policy choices; no clarification is required.
Infrastructure registries remain authoritative for machine-specific locations,
credentials and capacity. No CI, remote cache, custom verification controller,
new tooling-only test suite or dataset behavior change is in scope. Markdownlint
remains separate. Performance results are observations, not universal promises.

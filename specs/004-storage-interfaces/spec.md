# Feature Specification: Storage and interface failure contracts

**Feature Branch**: `fix/review-bugs-20261004`
**Created**: 2026-10-04
**Status**: Clarified
**Input**: Repair reviewed storage and interface failures while preserving successful workflows.

## User Scenarios & Testing

### User Story 1 - Safe storage transfers (Priority: P1)
Users receive truthful per-object outcomes while independent transfers finish.
**Independent Test**: Fail an upload, reject unsafe sync listings, and fetch through an unwritable corrupt cache.
**Acceptance Scenarios**:
1. Given an upload authorization wrapper failure, when a batch runs, then the failed object is counted and its independent peer finishes.
2. Given a noncanonical key or colliding destination anywhere in a listing, when sync runs, then no destination is written.
3. Given a directory at an image destination or an undeletable corrupt cache, when fetching, then no directory is removed and cache degradation is reported.

### User Story 2 - Reliable configuration and command feedback (Priority: P1)
Users can edit settings, remove obsolete ignored IDs, and interpret diagnostics.
**Independent Test**: Invoke commands with invalid typed configuration, selected profiles, and mocked required/optional doctor outcomes.
**Acceptance Scenarios**:
1. Given invalid timeout/config values, when CLI executes, then it exits with an actionable diagnostic without traceback.
2. Given only an enabled-state change, when ClearML setup completes, then the state survives reload.
3. Given a deleted ignored task ID, when removal executes, then the local entry is removed without requiring the task remotely.
4. Given a selected profile, when credentials are missing, then the selected profile is named.
5. Given required failures or only optional warnings, when doctor executes, then its exit code distinguishes those cases.

### Edge Cases
Empty/dot/dotdot project names, slash/backslash/NUL, pre-existing escaping symlinks; doubled key separators; duplicate listing entries and symlink aliases; zero/None/positive/negative/infinite/NaN timeouts; read-only cache directories; unavailable credential providers; disabled optional checks.

## Requirements

### Functional Requirements
- **STOR-001**: System MUST Count actual upload-wrapper failures per object, complete independent transfers, and do not retry authorization failures indiscriminately.
- **STOR-002**: System MUST Warn and use an uncached fallback when corrupt local cache entries cannot be deleted or repaired; fetch must continue.
- **STOR-003**: System MUST Validate every S3-sync destination before writing; reject noncanonical paths and destination collisions; preserve distinct object identity and truthful totals across worker counts.
- **STOR-004**: System MUST Count only regular files as cache hits; directory destinations fail without removal.
- **UI-001**: System MUST Encode project names as contained cache components; preserve logical project names.
- **UI-002**: System MUST Render typed configuration validation failures at the CLI boundary with actionable diagnostics and no traceback.
- **UI-003**: System MUST Reject negative and nonfinite data timeouts; preserve None/zero defaults and positive seconds.
- **UI-004**: System MUST Persist the selected ClearML enabled state even when mappings are unchanged.
- **UI-005**: System MUST Remove stored ignored task IDs without requiring remote task existence in noninteractive CLI/API flows.
- **UI-006**: System MUST Credential hints identify the selected configuration path, including explicit Connection.config_path.
- **UI-007**: System MUST Doctor exits zero when required checks succeed and one when required checks fail or cannot run; optional warnings and disabled checks do not fail.
- **OPS-003**: System MUST Unknown mutation profiles exit nonzero before mutation starts (parent implementation ownership).

### Key Entities
- Transfer: remote key, contained destination, one outcome.
- Configuration: logical project names, selected path, validated timeout, persisted enabled state.
- Doctor check: required, optional, or disabled, with explicit outcome.

## Success Criteria
- **SC-001**: Every requested transfer has exactly one counted outcome.
- **SC-002**: Unsafe sync input causes zero destination writes.
- **SC-003**: Every rejected config and required diagnostic failure exits nonzero without a traceback.
- **SC-004**: Stored enabled-state changes and stale-ID removals survive reload.

## Assumptions
Optional image-cache/S3 diagnostics are advisory; CVAT host and credentials are required. Existing cache-file contents are accepted as complete regular files; image decoding is outside scope. Existing project names without unsafe characters retain their directory spelling. Related write safety is owned by [002](../002-cvat-write-safety/spec.md); dataset correctness by [003](../003-dataset-correctness/spec.md).

## Clarifications
Session 2026-10-04: delegated requirements settle all material choices; no questions remain.

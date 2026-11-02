# Feature Specification: Managed datasets

**Feature Branch**: `feat/004-managed-datasets`
**Created**: 2026-11-02
**Status**: Approved for implementation
**Input**: Implement the approved conversational plan for strict shared/personal configuration, migration, mixed CVAT/S3 sources, external transformation, stable splits, CVAT feedback and reviewed ClearML publication.

## User Scenarios & Testing

### US1 — Shared project configuration (Priority: P1)
Users attach one authoritative shared configuration while keeping credentials, local paths and runtime preferences personal. Upgrade proposes a redacted split and requires user verification before activation.
**Independent test**: attach a shared file, reject a personal mapping override, migrate a legacy file with cancellation and interrupted activation recovery.
**Acceptance**: explicit path overrides environment selection which overrides the saved reference; no shared value is overlaid from personal config; existing shared files are never overwritten during attachment/migration.

### US2 — Incremental mixed-source assembly (Priority: P1)
Users fetch a complete candidate from multiple CVAT projects and additional annotation CSV objects in S3. Unchanged completed task annotations are reused from the published snapshot after live metadata checks.
**Independent test**: combine two CVAT projects and one S3 CSV; a second fetch performs zero annotation downloads for unchanged completed tasks.
**Acceptance**: task/label/registry changes invalidate reuse; missing sources fail; S3 changes replace the source contribution; provenance is explicit and task supersession remains project-local.

### US3 — Transform, split and prepare (Priority: P1)
Users run any external script, pass its resulting annotation CSV, and receive stable splits plus diagnostics and a reviewable clean dataset.
**Independent test**: arbitrary filtered/new rows prepare with deterministic 60/20/20 targets and no duplicate-content split leakage.
**Acceptance**: source evidence survives transformations; local images are required; unknown lineage is retained as unmapped; explicit overlap decisions and cleanup are enforced.

### US4 — Feedback and publication (Priority: P1)
Users report traceable errors to existing CVAT frames and publish a clean combined dataset without modifying annotations or job status.
**Independent test**: repeated feedback does not duplicate issues; partial delivery blocks publication; a ready preparation publishes exactly three files.
**Acceptance**: untraceable findings remain local; changed parent/source/config/media blocks stale publication; legacy datasets require one source refresh.

### Edge Cases
Missing/read-only shared files; duplicate source/destination identities; ambiguous migrated project names; unknown legacy fields; cancellation/interrupted migration; removed/reopened/empty tasks; label renames; same filename with different bytes; identical images from multiple sources; too-small splits; source changes after preparation; feedback-only metadata updates; partial remote creation.

## Requirements

### Functional Requirements
- **FR-001**: Separate versioned personal settings from authoritative shared project definitions; shared-owned values cannot be overridden personally.
- **FR-002**: Resolve shared selection explicit argument, then CVETA2_PROJECT_CONFIG, then saved personal reference; invalid selections fail without fallback.
- **FR-003**: Setup attaches shared files without editing them; policy writers target shared storage while local cache writers stay personal.
- **FR-004**: Upgrade detects mixed legacy configuration, previews a redacted split, requires approval, preserves a protected backup and supports cancellation/idempotent interruption recovery.
- **FR-005**: Preserve unknown legacy values in backup, expose ambiguities, and never invent project identities or revive retired publication settings.
- **FR-006**: Named datasets combine multiple CVAT projects and exact s3:// CSV objects into one exact ClearML destination.
- **FR-007**: Check task metadata; reuse only unchanged completed tasks, refreshing changed/new/reopened tasks and accounting for deletion.
- **FR-008**: Invalidate relevant reuse for CVAT label changes and external registry changes; support force refresh.
- **FR-009**: Retain all four original CVAT partitions and empty-task evidence; task-ID recency/deletion precedence is source-local.
- **FR-010**: Capture strict UTF-8 S3 annotation CSVs with content hashes and provenance; replace their contribution on change without downloading images or inventing task IDs.
- **FR-011**: Accept arbitrary externally transformed CSVs, preserving independent source evidence and reporting untraceable lineage honestly.
- **FR-012**: Assign stable content-identity splits with 0.6/0.2/0.2 targets and seed 42; preserve previous assignments and prevent identical-content leakage.
- **FR-013**: Require explicit source selection/exclusion for overlapping images, reject filename/content conflicts, and re-review changed overlap membership.
- **FR-014**: Apply existing training validation, class policy and whole-image quarantine; require explicit cleanup acceptance and training viability.
- **FR-015**: Create deduplicated frame review issues only for unambiguous CVAT provenance; leave annotations/status/human issues unchanged; block publication on failed mapped delivery.
- **FR-016**: Publish exactly dataset.csv, dataset.yaml and tasks.yaml, with complete versioned source snapshots in tasks.yaml and no images/ZIP.
- **FR-017**: Bind preparation to parent, relevant resolved shared definition, source evidence, transformed input and media; recheck before publishing stable bytes.
- **FR-018**: Preserve legacy readers/standalone behavior except documented strict-configuration changes; adopt existing datasets through one refresh.
- **FR-019**: Expose inspect/version/fetch/prepare/diff/feedback/publish CLI and prompt-free API operations with machine-readable inspection.
- **FR-020**: Keep SDK/filesystem effects behind ports and maintain documentation, companion usage skill, architecture checks, live integration isolation and Git-tag-only release gates.

### Key Entities
PersonalConfig; ProjectConfig; DatasetDefinition; SourceDefinition; SourceSnapshot; TaskSnapshot; ManagedPreparation; FeedbackFinding; Publication.

## Success Criteria
- **SC-001**: One dataset can combine two CVAT projects and one S3 annotation CSV with traceable source ownership.
- **SC-002**: An unchanged subsequent fetch performs zero task annotation downloads for reused tasks.
- **SC-003**: Migration activates no changes before user verification; cancellation and each interrupted activation recover without lost original data.
- **SC-004**: Repeated preparation preserves image split assignments, and identical content never crosses splits.
- **SC-005**: Feedback retries create no duplicate issues and no failed mapped delivery is reported as successful publication.
- **SC-006**: Each successful managed publication contains exactly the three contracted files and supports the next incremental fetch.

## Clarifications
All material choices were resolved in the conversation: one CVAT server, combined datasets, live task metadata checks, either label source invalidates reuse, opaque user-executed transformation, unmapped findings local, exclude-and-publish with cleanup, attach-only setup, strict shared ownership and reviewed migration.

## Accepted follow-up — cold start (2026-11-02)

- **FR-021**: Configured mappings must fetch/prepare with no ClearML dataset or destination project yet. Parent identity remains null; setup/fetch/prepare create no remote dataset. Publication creates the first finalized version without parent IDs; a later fetch reuses that version.
- **SC-007**: Unit and owned live mixed-source scenarios demonstrate absent-parent preparation, first publication, then unchanged-task reuse.

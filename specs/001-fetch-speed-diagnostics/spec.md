# Feature Specification: Faster fetches and actionable CVAT errors

**Feature Branch**: `feat/fetch-speed-diagnostics`
**Created**: 2026-10-28
**Status**: Accepted; released as v0.12.0
**Input**: Implement the supplied faster-fetch and CVAT-diagnostics plan.

## User Scenarios & Testing

### User Story 1 - Fetch the same dataset with less work (Priority: P1)

An operator exports annotations and images without redundant network requests,
filesystem resolution or temporary CSV writes.

**Why this priority**: Image and annotation latency affect every dataset export.
**Independent Test**: Compare outputs and counted effects for identical cold,
warm, fallback, large-image and annotation-heavy workloads at fixed workers.

**Acceptance Scenarios**:

1. Given at most 2,000 uncached canonical images, downloading needs one GET per
   image, no HEAD or listing; missing keys alone enter prefix/basename fallback.
2. Given more than 2,000 uncached images, listing occurs first; images cached at
   their expected canonical destinations require zero S3 calls. Transfer retries
   and atomic destination replacement remain.
3. Given repeated annotation rows, confinement/resolution scales with unique
   destinations, with lexical and symlink-escape rejection preserved.
4. Given ordinary fetch, no temporary task CSV or `.tasks` directory is created,
   written or removed. `save_tasks=True` preserves debug CSV contents and order.
5. Given filtered project export with cache pruning, the complete inventory
   snapshot protects ignored/unfinished/unselected tasks. Standard full fetch lists
   once; promotion precedes a fresh inventory. Later deletions reconcile next run.

### User Story 2 - Identify a failing CVAT request (Priority: P1)

An operator or Python caller can identify the actual failing HTTP request and
where to investigate, including failures inside pagination and issue comments.

**Why this priority**: Current retry exhaustion can lose status and request IDs.
**Independent Test**: Controlled HTTP failures at bootstrap, list pages and comments
produce typed, sanitized diagnostics, contextual retries and the established policy.

**Acceptance Scenarios**:

1. Given 500/502/503/504, the actual operation, HTTP method, sanitized endpoint,
   resource IDs, UTC timestamp, status, available correlation IDs and bounded
   response summary are available in logs/errors. Backend or gateway investigation
   suggestions distinguish evidence from hypotheses.
2. Given SDK status retry exhaustion, final status survives without changing
   retry budgets/method restrictions or shared pool settings. Default task-level
   5xx skips with a summary; strict mode raises; exhausted 429 aborts.
3. Given optional issue retrieval failure, output explicitly reports incomplete
   issue retrieval and does not make that result a valid completed-task cache.
4. Given concurrent clients/requests and then a success, failed request context
   stays isolated and cannot leak to subsequent errors. Credentials, cookies,
   unapproved headers/query values and raw HTML are absent from diagnostics.
5. Given existing Python error consumers, constructor positional arguments,
   exception identity, status and retry hint are unchanged; diagnostics are optional
   and keyword-only and their neutral type is exported from the exceptions facade.

### User Story 3 - Understand elapsed time and completeness (Priority: P2)

Operators see stage elapsed times and cached/fetched/skipped/degraded task totals.

**Why this priority**: Summed concurrent work time is not elapsed time or completion.
**Independent Test**: Inject deterministic clocks and mixed task outcomes.

**Acceptance Scenarios**:

1. Stage wall times are labelled separately from summed worker durations.
2. Retry logs identify cveta2 attempts/budget and wait duration, without claiming
   to count all SDK/HTTP attempts; skipped tasks and incomplete issues are summarized.

### Edge Cases

- S3 authorization, configuration and exhausted request connection failures abort;
  interrupted bodies and local writes count as transfer failures, never missing keys.
- Missing/fallback objects, a destination directory, concurrent atomic writers,
  symlink escapes, empty projects and partial task selectors retain safe behavior.
- Bootstrap/version checks and already-used injected SDK clients receive transport
  handling; version compatibility checks remain advisory.
- Incomplete issue retrieval retains its existing optional behavior, including its
  caught errors; mandatory task reads retain strict/429 abort policy.

## Requirements

### Functional Requirements

- **FR-001**: Remove redundant image HEAD calls for up to 2,000 pending images;
  retain large-batch listing, missing-only fallback, cache hits and bounded memory.
- **FR-002**: Preserve S3 failure categories, retries, atomic writes and recovery.
- **FR-003**: Memoize filesystem confinement/resolution per unique destination
  during each enrichment pass while preserving lexical validation.
- **FR-004**: Write task debug CSVs only when requested; preserve existing `.tasks`
  otherwise. Prune only with the complete post-promotion inventory snapshot.
- **FR-005**: Preserve worker limits, pipeline stages, fetch signatures, CSV
  contents/order, deletion precedence, recency and cache freshness.
- **FR-006**: Provide optional typed diagnostics on `CvatApiError` without breaking
  current positional arguments, identity, status, retry hint or exception causes.
- **FR-007**: Capture actual failed HTTP context and final retry-exhausted response,
  including nested requests; isolate concurrent and subsequent calls.
- **FR-008**: Copy each request retry policy and change only `raise_on_status`;
  preserve budgets, allowed methods, injected clients and advisory version checks.
- **FR-009**: Allowlist headers/query identifiers, redact secrets, omit cookies/raw
  HTML, bound summaries, and give evidence-aware investigation suggestions.
- **FR-010**: Report Russian stage timing, complete outcome totals, contextual
  cveta2 retry attempts/budget/wait, skipped tasks and incomplete issues.
- **FR-011**: Update baseline, architecture, Russian guides and companion portable
  usage/evaluation material; verify and complete the Git-tag-only release workflow.

### Key Entities

- Request diagnostic: immutable neutral failed-request facts, separate from SDK types.
- Fetch inventory: complete task-ID snapshot, distinct from selected tasks.
- Fetch totals: successful cached/live, skipped and degraded tasks; elapsed stage
  durations distinct from summed worker time.

## Success Criteria

- **SC-001**: Deterministic checks show N GETs/no HEAD/list for N <= 2,000 canonical
  cold images; zero remote image requests for a warm canonical-destination cache.
- **SC-002**: Ordinary export writes zero temporary task CSVs, lists tasks once,
  and path-resolution work grows with unique images rather than annotation rows.
- **SC-003**: Outputs are identical across worker counts and all preservation checks pass.
- **SC-004**: Controlled failure matrix proves request identification, redaction,
  concurrency isolation and default/strict/429 behavior through actual SDK transport.
- **SC-005**: Dated before/after measurements cover the five specified workload
  classes using identical worker settings, without a universal percentage promise.
- **SC-006**: Required focused, architecture/docs, lint/types, full-suite, mutation,
  packaging and serial live gates pass; fresh independent review has no blockers.

## Acceptance clarification — 2026-10-28

The zero-request image-cache guarantee applies when the expected canonical
destination exists. A stale frame name resolved through basename fallback still
requires alternate-key rediscovery on subsequent runs; its cached bytes are not
downloaded again. This preserves the existing fallback behavior and dataset/cache
formats. Controlled fallback measurements and the audit regression cover this
limitation separately from the warm canonical-cache case.

## Assumptions

The supplied plan resolves material behavior choices; no new flags, saved reports,
server investigation or worker tuning are in scope. Keep current dependencies and
supported Python >=3.12,<3.14. Diagnostic correlation values are untrusted, bounded
text; resource/query identifiers are allowlisted. Optional-issue policy is preserved.

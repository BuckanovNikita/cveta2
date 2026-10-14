# Feature Specification: Enforced clean architecture

**Feature Branch**: `refactor/clean-architecture`
**Created**: 2026-10-14
**Status**: Clarified
**Input**: Implement all six import-contract review findings using a full layer reorganization.

## User Scenarios & Testing

### User Story 1 - Preserve existing workflows (Priority: P1)

CLI and Python users can upgrade without rewriting supported calls or migrating datasets, caches, or recovery records.

**Independent Test**: Existing public API, CLI, configuration, conversion, fetch, upload and recovery regression suites retain their behavioral assertions.

**Acceptance Scenarios**:
1. Given a supported public import or call, when the reorganized package is installed, its signature, model identity across aliases, output and error behavior remain compatible.
2. Given an interrupted upload or existing cache, recovery and invalidation retain their previous ordering, keys and schemas.
3. Given an unavailable optional publisher, successful fetch results remain usable.

### User Story 2 - Substitute infrastructure (Priority: P1)

Maintainers can exercise application workflows with explicit test dependencies without constructing production clients, discovering configuration, or touching real storage.

**Independent Test**: Run workflows with recording ports and in-memory stores; import inner packages while SDK imports are blocked.

**Acceptance Scenarios**:
1. Given injected dependencies, application operations do not create concrete SDK/storage objects or read environment/configuration.
2. Given disabled caching, required local invalidation remains available without S3 access.
3. Given concurrent operations, results remain ordered and failure/cancellation semantics remain unchanged.

### User Story 3 - Prevent architectural regressions (Priority: P1)

Maintainers receive an actionable check failure when a dependency violates the declared architecture.

**Independent Test**: Introduce forbidden imports and effect calls in isolated fixtures; each intended rule rejects its negative case.

**Acceptance Scenarios**:
1. Domain-to-adapter, application-to-composition, port-to-implementation and canonical-to-facade dependencies fail checks.
2. SDK imports outside their approved adapters fail, including local and type-only imports.
3. New unclassified modules, forbidden adapter coupling and sibling cycles fail.
4. Package initializers do not eagerly load infrastructure when importing domain or application contracts.

## Requirements

- **FR-001**: Preserve documented APIs, public top-level modules, CLI arguments/messages/exit behavior, configuration precedence and public exceptions. Remove unsupported old internal packages after migrating repository callers. No deprecation warning is needed for preserved public APIs.
- **FR-002**: Establish domain, application, outgoing adapters, composition and incoming interfaces with inward source dependencies and no canonical imports of compatibility facades.
- **FR-003**: Application owns typed ports and receives its dependencies and resolved settings explicitly. Production dependency construction belongs to composition; no global service locator.
- **FR-004**: SDK imports and SDK failure translation belong to designated adapters. Neutral protocols and values must not import implementations.
- **FR-005**: Pure partition, merge, box validation and filename/key rules must not depend on storage or SDK implementations. Filesystem, configuration discovery, network, prompts and process/thread execution remain outside domain/application.
- **FR-006**: Enforce layers, module coverage, SDK import ownership, adapter independence, internal acyclicity, facade exclusion and effect ownership with executable positive and negative checks. Include local and type-only imports; do not hide violations with broad ignores.
- **FR-007**: Preserve task-ID recency, deletion precedence, strict promotion invalidation, local-only invalidation with caching disabled, cache degradation, per-object transfer outcomes, path containment and upload-resume write ordering.
- **FR-008**: Preserve cache/manifest/dataset schemas and paths, Unicode/text handling, polygon/confidence behavior, conversion materialization/cleanup, SDK timeouts, retry budgets and deterministic concurrent outcomes.
- **FR-009**: Migrate behavioral tests and mutation scope to canonical implementations without dropping assertions or reducing the mutation ratchet. New/moved Python code remains Python 3.10 compatible and introduces no future-annotations imports.
- **FR-010**: Finish documentation, full quality gates, live integration with owned cleanup, independent review, architecture acceptance and convergence before release. Git tags only; no package publication, deployment or GitHub Release objects.

### Key Entities

- Domain values: annotation models, partition results, storage identity and upload intent.
- Application contracts: CVAT API/session, cache/invalidation, image storage, dataset/conversion files, manifests, publication and execution.
- Resolved settings: explicit validated run/project values without loading effects.
- Architecture record: module ownership, dependency/effect rules, checks and review evidence.

### Edge Cases

Injected versus owned clients; missing credentials and selected profiles; absent ClearML; disabled caches with old entries; strict invalidation failure before remote writes; ambiguous task creation; completed manifests after cleanup failure; symlink/path collisions; nested frame names; duplicate basenames; UTF-8 CSV/YOLO/COCO outputs; worker failure and cancellation; imports through initializers and type-only blocks.

## Success Criteria

- **SC-001**: All supported public compatibility and existing behavior regression checks pass without data migration.
- **SC-002**: Every architectural boundary has a positive check and a representative rejected negative case; no runtime module is unclassified.
- **SC-003**: Application workflows run with supplied fake dependencies and inner imports succeed without infrastructure SDKs.
- **SC-004**: Required quality, mutation, integration and documentation gates pass; independent review accepts the complete diff and convergence leaves no unfinished required task.

## Assumptions

Keep existing Pydantic, pandas and Loguru dependencies. This changes ownership and dependency direction, not business behavior or storage formats. Public top-level modules remain supported; old internal service/client-operation packages are not compatibility promises. The existing resource location for bundled presets remains valid.

## Clarifications

### Session 2026-10-14

- Q: How much package reorganization? → A: Full domain/application/adapters reorganization with compatible public facades.
- Q: Preserve legacy implementation imports? → A: Public API only; migrate callers and remove unsupported old internal paths.
- All functional, data, interaction, reliability, dependency, edge-case, constraint and acceptance categories are clear from the accepted plan; no additional questions are required.

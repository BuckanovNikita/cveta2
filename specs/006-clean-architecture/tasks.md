# Tasks: Enforced clean architecture

## Phase 1: Setup and acceptance design

- [x] T001 Select feature, preserve existing work, create isolated branch, install locked dependencies and run baseline tests.
- [x] T002 Record specification, clarify compatibility decisions, plan module ownership and boundary contracts in this feature.
- [x] T003 Review requirements checklist and cross-artifact consistency; validate architecture record before code edits.

## Phase 2: Shared foundations (sequential)

- [x] T004 Add failing architecture regression fixtures in tests/test_architecture.py for each FR-006 boundary and isolated inner imports.
- [x] T005 Establish domain, application/ports, adapters, composition and interfaces paths; migrate shared domain values and neutral contracts, preserving public identities.

## Phase 3: Independent implementation streams

- [x] T006 [P] [US1] Move CVAT SDK translation to cveta2/adapters/cvat and operations to cveta2/application/client; inject session/image dependencies through explicit ports; retain public CvatClient construction in composition.
- [x] T007 [P] [US2] Refactor fetch/upload/resolve/task operations in cveta2/application/use_cases; inject cache, image, manifest, file, publisher and execution effects; implement storage adapters and preserve recovery/invalidation ordering.
- [x] T008 [P] [US2] Extract pure conversion/merge/baseline policy into cveta2/domain; inject dataset/materialization effects into application use cases and implement file adapters.
- [x] T009 [P] [US1] Split configuration resolution and settings; compose production dependencies and migrate CLI/API interfaces and public facades; keep root imports lazy and presets stable.

T006–T009 depend on T005. Parent assigns exclusive paths; shared port changes are serialized. T007 and T008 use separate file adapter modules. No integration cutover until all streams finish.

## Phase 4: Integration and regression prevention

- [x] T010 [US1] Migrate repository imports and monkeypatch targets, remove unsupported legacy implementation packages, preserve behavioral assertions and add recording-port compatibility tests.
- [x] T011 [US3] Replace incomplete import contracts with exhaustive layers, SDK protection, adapter independence and acyclic contracts; enforce canonical/facade and effect boundaries and verify all negative fixtures.
- [x] T012 [US1] Remove future-annotation imports from moved/new code, maintain Python 3.10 typing, reconcile Ruff/mypy/vulture and public documentation.
- [x] T013 [US3] Migrate mutation functions and revalidate equivalent mutants without reducing scope or ratchet.

## Phase 5: Acceptance and release

- [x] T014 Run complete quality gates, coverage, build, fast/full mutation and documentation checks; record dated results under evidence/.
- [x] T015 Run serial full live integration through the installed skill, clean exact owned tag and record cleanup evidence.
- [x] T016 Obtain fresh independent review after integration and parent verification; resolve findings and obtain acceptance.
- [x] T017 Run convergence, reconcile architecture.json with actual diff and checks, validate acceptance; update architecture/engineering guidance and final task evidence.
- [ ] T018 Complete authorized scoped Conventional Commits, merge-only main integration and semantic-release Git-tag-only release/push using repository skills and hooks.

## Coverage and checkpoints

US1 covers FR-001,007,008,009 through T006,T009,T010,T012–T015. US2 covers FR-002–005,007 through T005–T009 and T010. US3 covers FR-006,009,010 through T004,T011,T013–T018. All stories require complete acceptance; no reduced MVP. Existing regression suites are the behavioral baseline, with new boundary fixtures written before enforcement. Preserve exact public signatures, aliases, output formats, ordering and failure behavior throughout migration.

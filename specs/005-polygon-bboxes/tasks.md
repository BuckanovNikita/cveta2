# Tasks: Polygon bounding boxes

## Phase 1: Setup

- [x] T001 Inspect current main and create the isolated feature branch; capture baseline reproduction in specs/005-polygon-bboxes/research.md.
- [x] T002 Specify and clarify behavior in specs/005-polygon-bboxes/spec.md; generate plan and supporting design artifacts in this directory.

## Phase 2: Requirements gate

- [x] T003 Review specs/005-polygon-bboxes/checklists/geometry-cache.md and analyze spec.md, plan.md and tasks.md for consistency before code changes.

## Phase 3: US1 — Useful polygon boxes

Independent test: polygon-only frames become box rows in both fetch paths with
exact bounds and preserved metadata.

- [x] T004 [US1] Add failing triangle, concave/unordered-extrema, fractional, closed and outside-image polygon regressions plus full metadata/zero-rotation assertions in tests/test_extractors.py.
- [x] T005 [US1] Convert standalone polygons from all x/y vertices without clipping/rounding in cveta2/_client/extractors.py and warn per converted task/annotation; preserve rectangle mapping.
- [x] T006 [P] [US1] Exercise both fetch paths and deleted-polygon precedence with real CvatClient/FakeCvatApi output in tests/test_polygon_fetch.py.

## Phase 4: US2 — Malformed input diagnostics

Independent test: malformed inputs warn individually, contribute to one skip
summary and do not remove valid shapes from mixed tasks.

- [x] T007 [US2] Add malformed/mixed-shape regressions in tests/test_extractors.py and enforce even coordinate count of at least six, all finite values, min_x < max_x and min_y < max_y in cveta2/_client/extractors.py, with contextual warnings and skipped-count summary.
- [x] T008 [US2] Correct the track support warning in cveta2/_client/sdk_adapter.py and protect SDK polygon/track behavior in tests/test_sdk_adapter_conversion.py.

## Phase 5: US3 — Automatic cache refresh

Independent test: old entries from either layer miss, fresh fetch yields boxes,
and refreshed local/S3 reads preserve the output without replaying warnings.

- [x] T009 [P] [US3] Add explicit version-4 local/S3 rejection regressions in tests/test_task_cache.py and set CACHE_SCHEMA_VERSION to 5 with rationale in cveta2/task_cache.py.
- [x] T010 [US3] Exercise old-cache refetch and fresh polygon round trips through fetch orchestration in tests/test_polygon_cache.py; final green verification depends on T005.

## Phase 6: Documentation, verification and delivery

- [x] T011 [P] Update README.md, docs/cli.md, docs/images-and-cache.md, .specify/memory/architecture.md and specs/001-project-documentation/contracts/dataset-format.md for polygon approximation and cache refresh.
- [ ] T012 Run affected extractor/SDK/client/fetch/cache/conversion/docs tests and static checks; run configured coverage, typing, architecture and mutation gates; record evidence in specs/005-polygon-bboxes/evidence/verification-2026-10-12.md.
- [ ] T013 Obtain fresh independent review after integrated parent verification and converge spec/plan/tasks against the final implementation; record evidence in specs/005-polygon-bboxes/evidence/verification-2026-10-12.md.
- [ ] T014 Commit scoped files through hooks, merge to main, generate version/tag via semantic-release and push through configured gates; record release checks in specs/005-polygon-bboxes/evidence/verification-2026-10-12.md.

## Dependencies and parallel execution

T001–T003 precede implementation. T004 precedes T005; extraction owner performs
T007–T008 in that same stream. T009 can run alongside extraction, and T010 may
prepare fixtures before T005 but its successful integration check follows T005.
Parent can implement T006 and T011 while the two agents own disjoint source and
test files. T012 follows all streams; T013 follows parent verification. T014
requires accepted review and convergence, with push-stage checks after release.

Example: extraction agent owns T004/T005/T007/T008; cache agent owns T009/T010;
parent owns T006/T011 and final verification, convergence and delivery. Bounded
agents do not delegate or commit.

## Implementation strategy

First prove US1 at the extractor and fetch boundaries, then invalid-input
behavior and cache recovery. Ship all three together so previously cached users
receive the same corrected output. No partial release or new workflow tooling.

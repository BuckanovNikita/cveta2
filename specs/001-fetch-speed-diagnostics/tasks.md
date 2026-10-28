# Tasks: Faster fetches and actionable CVAT errors

## Setup and foundation

- [x] T001 Inspect source, current contracts, hooks, companion skill and unrelated changes; create spec/plan/research/contracts under specs/001-fetch-speed-diagnostics.
- [x] T002 Validate specs/001-fetch-speed-diagnostics/architecture.json planning phase and review requirements checklist/analyze coverage before implementation.

## US1 - Faster compatible fetches

Independent checks count effects and compare output/order/recovery across workers.

- [x] T003 [P] [US1] Add direct-GET, fallback/large/cache and failure/atomic regressions in tests/test_image_downloader.py and tests/test_s3_utils.py; establish failing observations before modifying S3 code.
- [x] T004 [P] [US1] Add inventory, .tasks preservation and unique-path regressions in tests/test_fetch_speed.py and relevant existing fetch tests before implementation.
- [x] T005 [US1] Implement small-batch direct GET, missing-only fallback, request/body classification and bounded atomic transfers in cveta2/adapters/s3/download.py and utils.py.
- [x] T006 [P] [US1] Implement complete inventory snapshot and opt-in task CSVs in cveta2/application/client/{fetch,shared}.py and application/use_cases/fetch.py.
- [x] T007 [P] [US1] Memoize confinement/resolution per destination in cveta2/adapters/files/dataset.py; preserve lexical/symlink checks.
- [x] T008 [US1] Benchmark baseline/current cold, warm, fallback, large-image and annotation-heavy workloads with identical workers using scripts/benchmark_fetch.py; record dated evidence.

## US2 - Actionable safe CVAT diagnostics

Independent checks use actual SDK transport against controlled HTTP routes.

- [x] T009 [P] [US2] Add failing request/retry/bootstrap/pagination/comment/concurrency/redaction regressions in tests/test_cvat_diagnostics.py.
- [x] T010 [US2] Add immutable neutral diagnostics and compatible keyword-only error metadata in cveta2/domain/errors.py and cveta2/exceptions.py.
- [x] T011 [US2] Implement transport context/sanitization and per-request copied retries in cveta2/adapters/cvat/{diagnostics,transport,connection,sdk_adapter}.py; retain causes and advisory version checks.
- [x] T012 [US2] Verify 500/502/503/504 default/strict and 429 abort, optional issues, old positional constructor, warm injected pools and concurrency in tests/test_cvat_diagnostics.py and related tests.

## US3 - Explain timing and incomplete results

Independent checks use injected clocks and mixed task outcomes.

- [x] T013 [US3] Add stage wall times and cache/fetch/skip/degraded summaries in cveta2/application/use_cases/fetch.py and Russian skip context in application/client/shared.py with tests/test_fetch_speed.py.
- [x] T014 [P] [US3] Add request-aware cveta2 attempt/budget/wait logging in cveta2/adapters/execution/retry.py with tests/test_retry_policy.py.

## Integration, acceptance and delivery

- [x] T015 Integrate and run focused regressions, import/effect/negative architecture and documentation checks; record specs/001-fetch-speed-diagnostics/evidence/verification.md.
- [x] T016 Update specs/baseline.md, .specify/memory/architecture.md, README.md and affected Russian docs/ guides for final behavior and diagnostics.
- [ ] T017 Update companion corp-skills/skills/cveta2 usage/evaluation material and validate its package/examples per MAINTENANCE.md; record source version/checks/commit in feature evidence.
- [ ] T018 Run required Ruff/mypy/Vulture/full coverage/fast and full mutation/packaging/lock gates and serial owned live integration; record actual results and cleanup in feature evidence.
- [x] T019 Obtain fresh independent read-only review of final integrated diff and Python/architecture evidence; fix findings and reverify before acceptance.
- [x] T020 Run convergence; reconcile complete task-owned diff/checks/review and validate architecture.json acceptance; append gaps rather than rewriting completed history.
- [ ] T021 Commit exact owned paths, merge to main, evaluate semantic-release with Git tags only, push authorized commit/tag refs and verify; record companion commit and release outcome.

## Dependencies and execution

T001–T002 precede all implementation. S3 T003→T005, application T004→T006/T007/T013,
and diagnostics T009→T010→T011→T012/T014 are independent bounded streams.
Parent owns S3/benchmark/specs/docs; application delegate owns fetch/files/tests;
diagnostics delegate owns CVAT/domain/errors/facade/retry/tests. Tests precede code.
Benchmark both base 13ffec2 and current via isolated imports with fixed settings.
Integrate all streams before T015–T018. T019 follows parent verification; then
T020 and T021. No deployment, package publication or installed-skill updates.

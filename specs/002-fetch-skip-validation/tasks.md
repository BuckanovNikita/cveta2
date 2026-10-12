# Tasks: Fetch without validation

## Phase 1: Setup

- [x] T001 Inspect current flow and create spec/design artifacts in specs/002-fetch-skip-validation/.

## Phase 2: Foundation

- [x] T002 Review requirements checklists and analyze spec/plan/tasks in specs/002-fetch-skip-validation/ before implementation.

## Phase 3: Accept finished work (US1)

Independent acceptance: eligible jobs are accepted in CVAT and rows enter the same
completed-only export. Default-off and repeated runs produce no redundant writes.

- [x] T003 [US1] Add failing eligibility/barrier/CSV tests in tests/test_fetch_skip_validation.py.
- [x] T004 [US1] Implement project promotion in cveta2/services/fetch.py with bounded task workers and sequential job updates.
- [x] T005 [US1] Add flag/echo/API forwarding in cveta2/cli.py, cveta2/commands/fetch.py, cveta2/api.py and adapter tests.
- [x] T006 [P] [US1] Add live transition/completion/membership/retry scenario in tests/integration/test_fetch_skip_validation.py.

## Phase 4: Preserve excluded work (US2)

Independent acceptance: excluded tasks have no writes and current CSV rules hold.

- [x] T007 [US2] Cover ignored, zero-job, unfinished/rejected/validation and special jobs plus ordering/deletions in tests/test_fetch_skip_validation.py.

## Phase 5: Recover from failures (US3)

Independent acceptance: a partial failure publishes nothing and retry only updates
remaining jobs; both cache layers are absent after a failed mutation attempt.

- [x] T008 [US3] Add strict pre-mutation invalidation in cveta2/task_cache.py and configured cache use in cveta2/services/fetch.py.
- [x] T009 [US3] Test read/write/cache failures, custom local/S3 settings, cache-disabled modes and retries in tests/test_fetch_skip_validation.py and tests/test_task_cache.py.

## Phase 6: Documentation and delivery

- [x] T010 [P] Update README.md, docs/cli.md, docs/python-api.md, docs/images-and-cache.md, .specify/memory/architecture.md and specs/001-project-documentation/contracts/dataset-format.md.
- [x] T011 Run relevant and full unit/docs/static/mutation checks and live lifecycle scenario; record dated evidence under specs/002-fetch-skip-validation/evidence/.
- [x] T012 Obtain fresh independent review after integration/verification, resolve findings and run converge; reconcile specs/002-fetch-skip-validation/tasks.md.
- [ ] T013 Complete configured commit/push/release gates and authorized Conventional Commit, main merge and semantic-release Git-tag-only release per CONTRIBUTING.md.

## Dependencies and parallel work

T001 → T002 → T003 → T004/T008 → T005/T007/T009 → T011 → T012 → T013.
T006 (live test authoring) and T010 (documentation) may run in parallel after T002
in exclusive files. Live execution waits for implementation. US2/US3 constrain
the same service flow and integrate before the feature is accepted.

## Implementation strategy

Implement and test the service boundary first, then adapters and edge cases.
Integration execution and repository gates follow the complete implementation;
no partial feature release. Preserve unrelated working-tree changes throughout.

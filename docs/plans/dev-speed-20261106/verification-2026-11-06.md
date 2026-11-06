# Verification: development speed (2026-11-06)

Plan: [plan.md](plan.md). Base: `a4f89cb` on branch `project-cleunap`.

## T0 Plan record

- `validate_architecture.py --record docs/plans/dev-speed-20261106/architecture.json --repo-root . --phase plan`: exit 0.

## T1 Phase 1 (commit bded204)

- `git commit` ran every hook in 5 min 1 s, including the old live gate:
  38 passed in 235.57 s under tag `cveta2-claude-20261106-integration-y5yr`.
- **A1, docs-only:** a README-only change ran ruff format and ruff check only;
  everything else was skipped. `prek run` took 0.89 s, against 17.3 s for the
  Step 0 docs commit under the old hooks.
- **A8 lockfile guard:** a staged `uv.lock` without `pyproject.toml` failed the
  `lockfile-guard` hook (exit 1, documented message). This was tested in a
  throwaway worktree.
- **D5:** `prek 0.5.10` ran the unchanged config and honoured `SKIP`,
  `fail_fast` and `verbose`. `prek validate-config` passed, and prek installed
  both the pre-commit and the commit-msg hooks.

## T2 Phase 2 (live tests in the suite, testmon, randomly)

- **Stopped stand, simulated** (`KUBECONFIG=/nonexistent`,
  `CVETA2_STAND_WAIT_TIMEOUT=20`, `-n auto`):
  - One Russian notice reached the terminal from the xdist worker.
  - After 20 s every live test failed with a single message naming the timeout
    and the reason.
  - All live tests ran on one worker (`gw1`, `@live` group).
- **First full `pytest --testmon`** (seed 525156811): 2852 passed and 1 failed
  in 4 min 58 s.
  - The failure was `test_e2e.py::test_get_project_tasks` (9 tasks instead of
    7). The random order had run task-adding live tests before it.
  - Fix: live tests keep their collection order in the slots the shuffle gave
    them. Two seeds give the same live order while the unit tests are shuffled.
- **Second full run** (seed 355390530): 2855 passed in 5 min 9 s. The run tag
  was stopped, and no `.run-tag` remained.
- **Third run, no code changes:** testmon reported "changed files: 0", ran no
  tests, and took 3.3 s.
- **Unit suite under randomly** (`-m "not integration"`): 2815 passed in 7.9 s.
- **Lifecycle tests:**
  - `tests/test_integration_lifecycle.py` passes: 62 tests, then more after
    adding the probe, wait, finish and child-env tests.
  - The gate and `test` command tests were removed together with those
    commands.

## T3 Phase 3 (mutation budget)

- `tests/test_mutation_tool.py`: 26 passed.
  - New: unjudged mutants ("not checked", "no tests") are counted and never
    reported as survivors, including under `--strict`.
  - New: `--max-functions` limits the run and lists the rest.

## T4 Phase 4 (fast-forward release and lock)

- The release lock was tested with `flock -n` on `.git/cveta2-release.lock`:
  while one holder ran, a second was refused, and the lock was free afterwards.
- `semantic-release --noop version --print` on `project-cleunap` reported
  "isn't in any release groups; no release will be made", as expected off
  `main`.
- The real fast-forward merge and release wait for the owner to end the
  cleanup.

## T6/T7 partial (C5, C7, A7, D3)

- **C5:** `scripts/session_status.sh` printed the branch against `main`, the
  uncommitted paths and an active run tag, and exited 0.
  - The hooks are `.claude/settings.json` and `.codex/hooks.json`.
  - Codex loading a project `.codex/hooks.json` is not verified yet. It needs a
    new Codex session, which may ask to trust the hook.
- **C7:** constitution 2.1.0 and `engineering.md` apply Spec Kit to new or
  changed capabilities only.
- **A7:** `dmypy run -- .` took 11.7 s cold and 0.15 s warm; no issues in 341
  files.
- **D3:** `deptry .` reported 16 DEP003 findings.
  - They are botocore, urllib3, numpy and prompt_toolkit, each imported
    directly and pinned by a declared parent.
  - They are ignored with a recorded reason; whether to declare them is the
    owner's decision.
  - The unused dev dependencies ipykernel, ipywidgets and matplotlib were
    removed.
- **Global A7/Phase 8:** agent-skills branch `feat/python-workflow-dev-speed`
  (`3edd79a`, unpushed and unmerged) updates the scaffold defaults.
  - It is not exported: the installed global exports match none of the
    agent-skills branches, and the checkout sits on another session's WIP
    branch.
  - The global-instruction line is deferred for the same reason.

## Independent review of bded204..928ab8b and its resolution

A fresh general-purpose reviewer read the diff without editing anything. Its
findings and their dispositions:

1. **High: teardown was armed only after `up()` succeeded.** Fixed:
   `prepare` now keeps or stops a failed or interrupted `up`. The restored test
   `test_a_failed_seed_still_tears_the_run_down` covers it.
2. **The lockfile guard failed `prek run --all-files`.** Fixed: the guard now
   passes when `uv.lock` is not staged. `prek run lockfile-guard --all-files`
   passed.
3. **A failing `room` and HTTP 4xx were waited on forever.** Fixed:
   - The probe now waits only on room WAIT, connection-level curl statuses
     (6, 7, 28, 52, 56, timeout) and HTTP 5xx.
   - Any other room failure, HTTP 4xx, or a missing tool fails at once.
   - Tests cover room exit 2, HTTP 404 and HTTP 503.
4. **The mutation budget orphaned mutmut's children.** Fixed: mutmut runs in its
   own session; when the budget is spent, the group gets SIGINT and then
   SIGKILL after 15 s. The new test
   `test_the_budget_interrupts_mutmut_and_its_children` checks that the forked
   child is gone; it ran in 1.8 s.
5. **The notice was hidden by the hook runner's output buffering.** Fixed: the
   notice is also written to `/dev/tty` when one exists. A human terminal has
   not verified this yet.
6. **Run variables leaked into unit tests on the live worker.** Fixed: the
   fixture records the exported names in `CVETA2_LIVE_EXPORTED`, an autouse
   fixture removes them for non-live tests, and teardown restores the
   environment.
7. **Stale `lifecycle test` references.** Fixed in `clearml_run.py`,
   `test_clearml.py`, `test_resilience.py`, `lifecycle.py` and
   `test_clearml_run.py`.
8. **No capture plugin:** fixed (falls back to stderr).
9. **Missing kubectl or curl:** fixed (clear error).
10. **Symlinked checkout path:** fixed (the item path is resolved).
11. **Release skill:** fixed. The fetch and the merge to `origin/main` now run
    inside the lock, the branch is passed as `$1`, and deptry is listed among
    the hooks that still run.
12. **`--amend` guard edge case:** accepted. A deliberate re-lock uses the
    documented `SKIP=lockfile-guard`.
13. **Coverage:**
    - Accepted: the dropped `live-cvat` coco8 re-run was already excluded from
      the old gate.
    - Added: `test_live_tests_are_marked_and_keep_file_order_under_any_seed`.
    - Restored: the TLS remedy in the identity failure message.
14. **Found while fixing, not by the reviewer:** dmypy crashed on a path subset
    inside clearml. The hook runs dmypy only on `.` and falls back to a full
    `mypy .` on any daemon failure.

After the fixes:
- The unit suite (`-m "not integration"`) had 2821 passed.
- `tests/test_integration_lifecycle.py` had 65 passed.
- `tests/test_mutation_tool.py` had 27 passed.
- ruff, vulture and lint-imports were clean.

## T5 Phase 5 test debloat

The work was split across five subagents, each owning a disjoint set of files
(fetch, upload, core, convert, tooling). The parent integrated it.
- **Hypothesis and inline-snapshot:** both were added in `5a90d44`, with a
  deterministic, deadline-free profile.
- **inline-snapshot was not used:** the large expected blocks became
  properties or shared helpers instead.

| Measure | Before (5d1aefc) | After |
|---|---|---|
| Unit test cases (`-m "not integration"`) | 2821 | 2591 |
| `def test_` functions, unit files | 1946 | 1576 |
| Unit test lines | 42457 | 38400 |
| Line coverage, unit tests only | 9436 / 10086 | 9436 / 10086 (one line was lost, then restored) |
| Branch coverage, unit tests only | 2362 / 2758 | 2362 / 2758 |
| Mutation, five modules, no budget | 1194 mutants: 1164 killed, 30 survived | 1194 mutants: 1158 killed, 36 survived |

**Coverage comparison.** The line and branch sets were compared per file. Only
`cveta2/adapters/s3/download.py:341` was lost: a malformed S3 response, a
`KeyError`, becoming a transfer failure. The deleted
`test_download_adds_listing_misses_and_transfer_failures` was restored.

**Mutation comparison.**
- The run used explicit-file mode with `--budget-seconds 0 --max-functions 0`
  on five modules:
  - `domain/merge.py`
  - `domain/partition.py`
  - `use_cases/fetch.py`
  - `upload/planning.py`
  - `convert/yolo.py`
- All 30 earlier survivors still survive, and there are six new ones. Each new
  one is `__mutmut_1`/`_2`, a pin on a default argument of an internal
  function:
  - `convert_to_yolo` (two survivors)
  - `convert_from_yolo`
  - `build_upload_plan`
  - `filter_frames_by_labels`
  - `_merge_datasets`
- Every production caller passes those arguments explicitly. The public API's
  defaults live in `composition/conversion.py` and its callers. They are
  accepted under the B8 policy.

**Properties.** New Hypothesis properties cover:
- the YOLO round trip and the COCO export structure;
- partition rules against a reference model, with pinned examples;
- merge precedence;
- the retry predicates and backoff;
- the CSV text and empty-cell round trip;
- the record image-name and frame-path rules;
- coordinate conversion.

The subagents checked the partition, merge and CSV properties against
hand-made mutants.

**Reviewed decision.** The deleted issue-creation default test is still
covered behaviourally by
`test_issues.py::TestSkipExistingIssues::test_a_normal_upload_does_not_read_the_issues_back`.

**Checks after integration:**
- strict mypy (336 files);
- ruff;
- vulture;
- lint-imports;
- the unit suite.

## Final checks and second review

**Full pre-merge check** on `b513825`: `uv run pytest --cov`, live tests
included, seed 3639565251.
- 2629 passed in 4 min 59 s, with total coverage of 92.23%.
- The run tag was stopped, and no `.run-tag` remained.

**Hypothesis exploration.** A side note pointed out that the fixed profile
checks the same 50 inputs on every run.
- Added the opt-in `HYPOTHESIS_PROFILE=explore` profile (random, 1000
  examples). It is documented in `engineering.md` and is part of the release
  skill's step 1.
- The whole unit suite under it: 2591 passed in 22.7 s, with no new failure.

**Independent review of the debloat** (`5a90d44..b513825`): no high-severity
finding. Dispositions:
1. **Mutation `child_env` no longer checked for MinIO, `INFRA_RUN_TAG` and
   `GIT_*`.** Restored
   `test_child_env_drops_stand_and_git_variables`; it now also covers
   `CLEARML_*` and `INTEGRATION_*`.
2. **8-worker fetch-once check reported missing.** False positive:
   `test_fetch_service.py::test_concurrent_fetch_produces_the_same_dataset_as_a_serial_one`
   asserts it, with `cvat=8`.
3. **Two shared-stand safety scans deleted.** Restored
   `test_the_source_embeds_no_root_credential` and
   `test_the_module_has_no_registration_path`.
4. **Lifecycle rejection of unknown arguments.** Restored.
5. **`split_deleted_rows` case that deleted nothing checks less.** Now asserts
   that the frame passes through unchanged.
6. **The label-picker prompt text is no longer asserted.** Accepted: it is
   interactive text, not CLI contract.
7. **The properties had no pinned `@example`s.** Added pinned examples:
   - YOLO: all three splits, `"001"`/`"NA"`, and corner boxes;
   - COCO: every split, an image with no boxes, and `"001"`/`"NA"`.

After the fixes:
- strict mypy (336 files), ruff and vulture are clean;
- the unit suite has 2595 passed;
- lint-imports kept 10 contracts;
- the architecture and boundary tests have 65 passed;
- the lifecycle and mutation tool tests have 84 passed;
- `validate_architecture.py --phase acceptance` exits 0.

## Open items (not done)

- **Real stopped-stand run.** A stop/start of a real stand, end to end, needs
  the owner's go-ahead, because it stops a shared stand.
- **Terminal notice.** The `/dev/tty` notice has not been seen in a human
  terminal yet.
- **Codex hook.** It is not verified whether Codex loads and trusts
  `.codex/hooks.json`.
- **Global exports.**
  - agent-skills `feat/python-workflow-dev-speed` (`3edd79a`) is unmerged and
    not exported. The installed global exports match none of the agent-skills
    branches, and the checkout is on another session's WIP branch.
  - The global-instruction line is deferred for the same reason.
- **Merge and release.** The real fast-forward merge and release (T4) wait for
  the owner to end the cleanup.
- **Owner decision on DEP003.** Whether to declare botocore, urllib3, numpy and
  prompt_toolkit as direct dependencies.

## Post-acceptance fix: data-only changes under testmon

- **The problem.** A probe appended a line to `cveta2/presets/default.yaml`.
  `pytest --testmon --collect-only` then reported "changed files: 0" and
  collected no tests: testmon tracks Python only.
- **The fix.** The `pytest` hook now runs `--testmon-noselect`, the whole suite,
  whenever a staged non-Python file sits under `cveta2/` or `tests/`.
- **Checked:** the file-detection pipeline, on a preset, on fixture JSON
  together with a `.py` file, and on Python-only changes.

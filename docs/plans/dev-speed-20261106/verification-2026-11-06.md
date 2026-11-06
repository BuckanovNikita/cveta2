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

# Development speed: maintenance plan

Date: 2026-11-06. Branch: `project-cleunap`. Tasks: [tasks.md](tasks.md); open items: [discussion.md](discussion.md); architecture record: [architecture.json](architecture.json).

## Context

On 2026-11-06 the owner reviewed a menu of options; this plan covers the approved items.
The goals are:
- commits and releases that skip checks which cannot find anything new;
- a smaller test suite;
- less churn between parallel sessions.

**Evidence the plan rests on (HEAD a4f89cb):**
- **Every commit runs every hook.** That includes the full unit suite (~30 s), mutmut (~40 s) and the live gate (232 s).
- **The release commit only bumps the version, yet it reruns the live gate.** Merges run no hooks at all.
- **Test code is 1.8x the source:** 48k lines of tests against 26k lines of `cveta2/`.
- **About 4k lines of tests cover tooling, docs or structure** rather than the package.
- **Many tests exist only to pin defaults or wording for mutmut.**
- **Fetch tests are spread over 10 files and upload tests over 8**, with known duplicates.

**Owner decisions:**

| Status | Items |
|---|---|
| Approved | A1, A2, A3, A4 (modified: keep mutmut, make it less strict), A5 (redefined), A6, A7 (global), A8 (plus extra lockfile restriction), B1–B9 (B2 replaced by deleting `test_docs.py`), C4, C5, C7, D1, D3, D5 |
| Rejected | A9 (no GitHub Actions), C8, D2 |
| Under discussion, saved for another session | C1, C2, C3, C6 (as a split into more granular files, not a merge), D4 |

## Workflow and ownership

- **Workflow.** This is development-tooling and governance maintenance, so it follows the lightweight path in `.specify/memory/engineering.md`.
  - The record lives in a new directory, `docs/plans/dev-speed-20261106/`: `plan.md`, `tasks.md`, `architecture.json` and dated verification evidence.
  - `architecture.json` records no package interface change, and is validated with `--phase plan` and `--phase acceptance`.
- **Governance edits.** A2, A5, C7 and B8 change governance. They amend `.specify/memory/constitution.md` (version bump plus a sync impact report) and `engineering.md`.
- **Branch.** All work continues on the current branch, `project-cleunap`; no merge into `main` first. The owner merges it, together with the new release flow, when the cleanup really ends.
  - Commits happen per phase on this branch.
  - Phase 4's fast-forward merge and release flow is implemented and dry-run tested (`semantic-release version --print`, plus a lock test), but the real merge and release wait for your end-of-cleanup signal.
- **Global work.** The A7 global part lives in the private `agent-skills` repository and is committed there separately.

## Step 0: save the open discussion

Write `docs/plans/dev-speed-20261106/discussion.md` (English) for a later session. It covers the open items, with the questions the owner raised:

- **C1: a worktree per session.** It should explain how this would help you:
  - Today, sessions share one checkout.
  - The live gate keeps everyone's unstaged edits stashed for minutes, so a parallel session can lose or interleave edits.
  - Two sessions can stage each other's files.
  - Separate worktrees remove both failure modes.
  - Costs: a `.venv` per worktree, and stand capacity when several live runs happen at once.
  - Open question: does this matter once A5 and A6 make the live part run only when affected?
- **C2: evidence outside the repository.** About 50 of the last 113 commits are bookkeeping. The open risk is losing context.
  - Middle options to discuss: commit trailers that hold the check results, or one evidence file per task written in the same commit as the change, never as a follow-up "record evidence" commit.
- **C3: short rebased branches.** It depends on A2 using fast-forward merges. To discuss: the maximum branch lifetime, and how to keep one open branch per session.
- **C6: split the instruction layers into more granular files.**
  - Today the large files are `engineering.md` (382 lines), `constitution.md` (195), `architecture.md` (347) and `baseline.md` (778).
  - The idea: many small topic files (hooks, releases, integration, conventions, …), so that parallel sessions touch different files and load less context.
  - To discuss: the boundaries between files, and whether this needs the generated `speckit-*` skills changed.
- **D4: a faster type checker** (basedpyright, ty or pyrefly), either alongside mypy or replacing it. To discuss: the strictness gap, and whether A7 (dmypy) already solves the speed problem.
- **Rejected items, recorded so they are not proposed again:** A9 (GitHub Actions), C8 (union merge driver), D2 (pytest-timeout).

## Phase 1: hooks and the lockfile

All changes are in `.pre-commit-config.yaml`, `pyproject.toml` and `engineering.md`.

1. **D5: switch the runner to `prek`.**
   - Add it to the dev group, run `prek install`, and remove `pre-commit` from the dev group.
   - The config format stays the same.
   - Update the setup line in `engineering.md` (`uv run pre-commit install`) and the hook docs.
2. **Delete `tests/test_docs.py` (replaces B2).** Then remove every reference to it:
   - `engineering.md`, the Verification, Documentation and Project skills sections;
   - the `--ignore=tests/test_docs.py` entry in `[tool.mutmut]`;
   - any skill text that names it.
3. **A1: path filters.**
   - mypy, vulture and pytest get `files: ^(cveta2/|tests/|scripts/|main\.py$|pyproject\.toml$|uv\.lock$)` and drop `always_run`.
   - ruff format and ruff check stay on all files; they take under 1 s.
4. **A3: drop slow hooks that find nothing.**
   - Remove the `count-lines` hook.
   - Move `uv build` from every commit to a hook filtered to `pyproject\.toml$`, so build metadata is still checked.
5. **A8: lock the lockfile.**
   - Replace the `uv lock` hook with `uv lock --check`, filtered to `pyproject\.toml|uv\.lock`.
   - Set `UV_LOCKED=1` for the hook commands, by prefixing the entries or using `env`, so `uv run` never re-locks silently. This is the "lock everything" step.
   - Extra restriction: a small local hook fails when `uv.lock` is staged without `pyproject.toml`. This stops unexplained re-locks. A semantic-release commit is exempt: either its `chore(release):` subject is detected in the commit-msg stage, or the hook is skipped explicitly from the release skill.
   - Recovery after the restriction fires: run `uv lock` deliberately in a dependency commit.

## Phase 2: one test suite, including the live tests (A5, A6, D1)

1. **A5: integration tests become a normal part of `pytest`.**
   - Remove the `integration-tests` hook.
   - Remove the `CVAT_INTEGRATION_HOST` collection switch, and the `integration` marker if nothing still needs it.
   - The stand lifecycle from `tests/integration/lifecycle.py` moves into a session-scoped fixture in `tests/integration/conftest.py`. The fixture:
     - runs the `room` preflight;
     - mints the tag with `infra.py newtag --project cveta2`;
     - sets up and loads the credentials;
     - cleans up by exact tag in a `finally` block;
     - uses the durable `cveta2-main` slot when on `main`.
     - waits for a stopped stand as described below.
   - Live tests run serially, as CVAT rate limits require. They are marked `xdist_group("live")` and the suite runs with `--dist loadgroup`, so one worker takes all of them while unit tests stay parallel.
   - `tests/integration/lifecycle.py` keeps only what the fixture reuses, plus a manual `cleanup` command for crashed runs.
   - Update the `running-integration-tests` skill, the user's memory note about integration tests, and the `release` skill.
2. **A6: `pytest-testmon` selects affected tests at commit.**
   - The commit hook runs `pytest --testmon -n auto --dist loadgroup` and does not enforce coverage.
   - The full suite plus `--cov` and `fail_under` runs at merge time (Phase 4) and with `pytest --testmon-noselect`, or plain `pytest`.
   - `.testmondata` is added to `.gitignore`; each worktree keeps its own.
   - Fixture or conftest changes: testmon tracks them by coverage. Document `rm .testmondata` as the reset.
   - Live tests are selected only when code they execute changes. That replaces the old coarse file filter.
3. **D1: `pytest-randomly`.**
   - Order is randomized per run, and the seed is printed.
   - It must also randomize under xdist, and the live group stays deterministic: if needed, use `-p no:randomly` for the live suite only.
   - Fix any order-dependent failures it uncovers.

**When the stand is unavailable: notify, then wait until it is back.** The owner stops the stands on purpose, so this case is normal and must not fail the run.
- **What the session fixture classifies as "stand down":**
  - the kubectl context is unreachable;
  - the stand's pods or deployment are scaled to zero, or not ready;
  - the connection to the CVAT, MinIO or ClearML endpoint is refused, or times out;
  - `room` answers WAIT (exit 3).
- **What fails at once, without waiting:** authentication errors, TLS errors (`tests/integration/stand_tls.py::find_tls_error`), a missing k8s-infra skill, and real test failures.
- **Notice.** On "stand down" the fixture prints one clear message in Russian, as the project's CLI-output convention requires. It says the stand is unavailable (possibly stopped), that the run waits for restore, and that Ctrl-C aborts. It names which stand failed and what was checked.
- **Waiting.**
  - It polls the health check with backoff, from 15 s up to 60 s.
  - It prints a short heartbeat every 5 minutes, showing elapsed time and the last error.
  - When the stand is back, it says so and continues. Setup, tag minting and testing resume normally.
- **The wait has no limit by default.** An optional env variable, `CVETA2_STAND_WAIT_TIMEOUT` (seconds), caps it. When the cap is reached the run fails with the same clear message, not a traceback.
- **Ctrl-C or SIGTERM** stops the wait cleanly. Nothing has been minted yet, so there is nothing to clean up. If a stand drops after the tag was minted, cleanup by exact tag runs in `finally`; if cleanup itself cannot reach the stand, the tag is printed for the manual `lifecycle.py cleanup`.
- **Only the live group waits.** Unit tests on the other xdist workers keep running. testmon (A6) means the wait happens only when live tests were selected.
- **Agent sessions.**
  - A commit or test run that may wait is started with `run_in_background`, and its output file is watched with Monitor, so the 10-minute Bash timeout cannot kill it mid-wait.
  - The agent reports "waiting for stand restore" to the user instead of retrying, skipping or using `SKIP=`.
  - The `running-integration-tests` skill and `engineering.md` say this.
- **Hook interaction.** While a commit waits, pre-commit/prek keeps unstaged changes stashed. The notice says so: do not edit the working copy until the run finishes.
- **Tests for the waiting logic:**
  - Unit tests with a fake health probe and clock cover the notice, the backoff, the heartbeat, recovery, the timeout and Ctrl-C.
  - The immediate-failure classes are covered too.

## Phase 3: mutmut stays, less strict (A4 modified)

Mutation testing keeps running at commit on `cveta2/` changes. Assumptions about what "less strict" means; correct them if wrong:

- **A time and mutant budget.** `scripts/mutation.py` gets a `--max-mutants` or `--budget-seconds` cap with a default of about 30 s. Functions left untested by the budget are listed, not run.
- **Survivors are informational only.** B8 says that a survivor in presentation, default arguments or wording needs no new test; a person triages only behavioural survivors.
- **Shorter output.** Print counts plus at most N survivor diffs.
- **Keep the existing test tooling.** Keep `tests/test_mutation_tool.py`, trimmed under B1, and the `mutation-testing` skill, updated.

## Phase 4: releases and `main` (A2, C4)

- **A2: release without rerunning the gate.**
  1. Before the merge, on the branch tip, run the full suite including live tests: `prek run --all-files` plus a full `pytest --cov`, with coverage enforced.
  2. Rebase onto `main` and merge with `git merge --ff-only`, so the `main` tip is the commit that was checked.
  3. The release skill commits the version bump with `SKIP=pytest,mypy,vulture,mutmut,lockfile-guard`. It still runs ruff, `uv lock --check` and `uv build`.
  - Update `engineering.md`: "main changes only by merge" becomes "by fast-forward merge of a checked branch".
  - Update the constitution line 94 wording, and the `release` skill.
- **C4: one release at a time.**
  - The release skill wraps the merge, the release and the push in `flock .git/cveta2-release.lock`.
  - A second session waits, or fails fast with `-n` and a clear message.

## Phase 5: test debloat (B1, B3–B9)

Do this when no other branch is changing tests, because it touches many files.

1. **B8 (policy, first).** Add rules to `engineering.md`:
   - Do not add tests that only kill mutants on defaults or wording.
   - Extend an existing module test file instead of creating a new file per origin ("regressions", "architecture").
   - Assert wording only for the CLI contract output.
   - Keep `fail_under` at 90 unless the debloat itself drops coverage; then decide with evidence.
2. **B7 (first measurement).**
   - Run the suite once with `--cov-context=test`.
   - A one-off script in `$CLAUDE_JOB_DIR/tmp` (not committed) lists the tests whose covered lines and branches are a subset of other tests'.
   - Its output guides B3 and B4.
3. **B1: cut the tooling tests to smoke tests.** They stay in the one suite, and testmon (A6) runs them only when their files change.
   - Files: `test_integration_lifecycle` (shrinks with A5), `test_seed_cvat`, `test_mutation_tool`, `test_mutation_isolation`, `test_cvat_stand`, `test_clearml_run`, `test_integration_tool_boundaries`, `test_stand_tls`.
   - Delete the self-referential source-text and wording assertions.
4. **B3: fold the non-structural architecture and regression files into their module test files**, deleting duplicates.
   - Files: `test_client_architecture`, `test_conversion_architecture`, `test_workflow_architecture`, `test_architecture_mutation_regressions`, `test_fetch_audit_regressions`, `test_managed_migration_regressions`, `test_managed_mutation_policy`, `test_managed_mutation_settings`.
   - Keep `test_architecture.py` (structural).
5. **B4: consolidate the fetch and upload clusters.**
   - Parametrize the paired `fetch`/`fetch_task` tests in `test_api_fetch.py`.
   - Remove the ignore/completion/cache scenarios that are repeated in several files.
   - Move `_FakeApiWithStorage`, now in `test_fetch_service.py` and `test_task_cache.py`, into `tests/fixtures/fake_cvat_api.py` as a `storage=` option.
   - Use `tests/helpers.py::make_cs_info` instead of the local copy in `test_image_uploader.py`.
6. **B5: parametrize.** Targets: `test_merge`, `test_interactive` (`TestRequireInteractive`), `test_models`, `test_upload_helpers`, `test_fetch_service` and `test_doctor_checks`.
7. **B6: Hypothesis.** Add it to the dev group, with a `derandomize` profile for commits, and use the `property-based-testing` skill.
   - Write property tests for the YOLO and COCO round trips, CSV↔model, `domain/partition`, merge precedence and `retry_policy`.
   - Remove the example tests that the properties subsume.
8. **B9: `inline-snapshot`.** Use it for the large expected DataFrame, CSV and YAML blocks in the convert, merge and review tests.

**Delegation:**
- B3, B4, B5 and B6 split into independent subagent workstreams, one per test cluster: fetch, upload, merge/models/interactive, convert/partition.
- Each subagent gets exclusive ownership of its files.
- The parent integrates their work, reruns B7 to confirm that no package lines or branches were lost, and orders a fresh independent review.

## Phase 6: sessions and workflow (C5, C7)

- **C5: a SessionStart hook in both hosts.**
  - Claude: `.claude/settings.json` in the repository. Codex: the equivalent hook config.
  - It runs a small `scripts/session_status.sh` that prints:
    - the branch, and how far it is ahead of or behind `main`;
    - other worktrees and branches;
    - a dirty-tree summary;
    - a held release lock (C4);
    - any active live run tag.
  - The output is capped at about 10 lines.
  - Record the intended host difference, per your global "keep Claude and Codex in sync" rule.
- **C7: Spec Kit only for features.**
  - Amend the constitution and `engineering.md`. A behaviour-changing bug fix or refactor uses a plain `docs/plans/<task>/plan.md`, or just the commit, instead of the 8-stage sequence.
  - It still needs a failing observation and verification, per your global bug rule.

## Phase 7: global and auxiliary tools (A7, D3)

- **A7: dmypy, set up once globally.**
  - In `/mnt/wsl/data/nkt/agent-skills/skills/python-project-workflow`, add a standard hook snippet for its uv/hatchling scaffold and a short note on daemon state per worktree.
  - The snippet is `uv run dmypy run -- <paths>` with a fallback to `mypy` when the daemon is in a bad state.
  - Reinstall the skill exports, following the maintenance sync.
  - In cveta2, change the mypy hook to `dmypy run`, and add `.dmypy.json` to `.gitignore`.
- **D3: `deptry`.**
  - Add it to the dev group, and run it as a hook filtered to `pyproject.toml`, `uv.lock` and `cveta2/`.
  - Resolve its first findings; `ipykernel`, `ipywidgets` and `matplotlib` look unused.

## Phase 8: global setup changes

These changes live outside this repository, in their authoritative sources, following "Instruction and skill sources" in your global instructions. They are committed in their own repositories, with Claude and Codex kept in sync.

| Change | Where | Why |
|---|---|---|
| dmypy hook snippet and daemon notes (A7). New-project scaffold defaults: `prek` instead of pre-commit, `UV_LOCKED=1` in hooks, a `uv lock --check` hook, path-filtered heavy hooks, `pytest-testmon` and `pytest-randomly`, `deptry` | `/mnt/wsl/data/nkt/agent-skills/skills/python-project-workflow` (scaffold and references) | The owner asked for these to be set up once and reused across projects |
| Install `prek` once as a global tool (`uv tool install prek`). Document it in the machine-environment part of global instructions or the skill | `agent-skills/instructions/global.md`, only if a machine fact is needed; otherwise the skill reference | Faster hook runner across projects; a per-project dev dependency stays as the portable fallback |
| A rule that live tests are part of the normal suite on this machine, and that infra is assumed available | The machine-environment section of `agent-skills/instructions/global.md`, kept short, with details in the k8s-infra run contract | A5 premise; a portable project rule must not contain machine facts |
| Check that the `k8s-infra` run contract supports a pytest session fixture: `newtag` and `cleanup` from inside pytest, `INFRA_HARNESS` defaults, and the concurrent live-run cap. Request changes only if something is missing | `/mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra` (authoritative checkout; read first, edit only if needed) | The A5 fixture replaces the lifecycle CLI as the caller |
| Update the memory note about integration tests (no separate gate; it is a session fixture inside pytest) | Memory `integration-tests-on-k8s-cvat-stand.md` | It describes the old lifecycle gate |
| If wanted, the C5 status hook in every repository rather than only cveta2: a global SessionStart hook in the Claude and Codex settings, recorded in the `personal-automations` inventory | Global host settings plus the personal-automations skill | Optional. The default stays project-level unless the owner says otherwise |
| Regenerate the installed exports, run the synchronization checks, and record intentional differences between hosts | `/mnt/wsl/data/nkt/.agents/maintenance/manifest.json`, via its sync | Required after any shared skill or instruction change |

There is no change to the global release, commit or evidence rules: A2's fast-forward merge is a cveta2 project rule.

## Verification

- **Speed, before and after.** Use `time git commit` for:
  - a docs-only commit (target: a few seconds, no pytest or mypy);
  - a small code commit (testmon selects only a few tests, with the mutmut budget applied);
  - a `uv.lock`-only commit (rejected by the guard).
- **Correctness of the full run.**
  - A full `pytest --cov` passes with coverage of at least 90%, and the live tests run serially in one xdist group.
  - Exact-tag cleanup is proven with the k8s-infra listings.
  - `prek run --all-files` is green.
- **Stand-down path, end to end.**
  1. Scale the CVAT stand down through the k8s-infra skill's sanctioned stop, which is your normal way of stopping it.
  2. Start a run that selects live tests, and confirm it prints the notice and the heartbeats.
  3. Start the stand again, and confirm the run resumes and passes with exact-tag cleanup.
  4. Repeat with a timeout set and with Ctrl-C.
  - This needs your go-ahead at the time, because it stops a shared stand.
- **Debloat.**
  - Report test line and test counts before and after (baseline: 47,956 lines and 2,835 tests).
  - The B7 coverage-context comparison shows no package lines or branches lost.
  - `scripts/mutation.py --base main` shows no new behavioural survivors.
- **Releases.**
  - `semantic-release version --print` gives the expected version.
  - A real release follows the new skill: the merge is fast-forward only, the release commit skips the heavy hooks, and a second session is blocked by the lock.
  - The tag is confirmed with `git ls-remote`.
- **Hooks and governance.**
  - The SessionStart output appears in a new Claude session and a new Codex session.
  - The architecture record is validated with `--phase acceptance`.
  - A fresh independent review covers the whole diff.
- **Global changes.**
  - Run agent-skills skill validation, then the maintenance sync check: Claude and Codex exports match their sources.
  - Scaffold a new throwaway project in the job temp directory and confirm that its hooks run with `prek`, `dmypy` and `testmon`. Delete it afterwards.
- **Release.**
  - Commit the work per phase as Conventional Commits on `project-cleunap`.
  - Push the branch only on request.
  - The merge into `main` and the release through the updated `release` skill happen when the owner ends the cleanup.

# Development procedures

This document owns every development command and procedure, for contributors and agents.
Rules that apply to every task live in [AGENTS.md](../AGENTS.md), code structure in
[architecture](architecture.md), and product behavior in the feature files under
`docs/feature/`.

## Worktree setup

Set up each worktree from its root:

```bash
uv sync --locked
bash scripts/install-hooks.sh
```

Live tests also need `kubectl` with the `docker-desktop` context. They deploy their own
services; they need no other repository, Helm, shared stand or local CA.

## Verification

[Taskfile.yml](../Taskfile.yml) owns the commands and their order. Invoke a stage as
`uv run --locked task --exit-code <stage>`; `--exit-code` keeps a child's failure status.
Clear an inherited `UV_PROJECT_ENVIRONMENT` before the outer `uv run`, so uv uses this
worktree's `.venv`. Task then pins every child command to this worktree's `.venv`,
testmon data, coverage file and Ruff and mypy caches, even when cache overrides were
inherited. In hooks, `scripts/git-hook.sh` sets `UV_PROJECT_ENVIRONMENT` itself.

Task keeps no freshness cache: commands run in sequence and only the tools reuse their
own incremental data. Each `verify` invocation runs every static command once, even when
testmon omits unaffected tests. There are no success receipts, shared result cache or CI
verification job. Task freshness, timestamps and interrupted runs never establish
completion.

### Stages

| Stage | What it runs |
| --- | --- |
| `fix` | Safe Ruff fixes (`--no-unsafe-fixes`) and Ruff formatting; never stages |
| `check` | `uv lock --check`, `ruff check`, `ruff format --check`, `lint-imports`, `mypy`, `vulture`, `deptry` |
| `test` | testmon-affected unit tests; excludes `tests/integration`, its conftest included |
| `test-full` | Every unit test, refreshing testmon history |
| `build` | `uv build` into a uniquely owned temporary directory, removed afterwards |
| `verify` | Development verification: `check`, then `test`; builds no distribution |
| `infra-check` | Read-only bounded preflight of the live-test cluster |
| `integration` | `infra-check`, then the live tests under `CVETA2_TASK_VERIFICATION=1` |
| `properties` | Unit tests under the `explore` Hypothesis profile, with `-p no:randomly` |
| `mutation` | [Mutation report](#mutation-report); arguments follow `--` |
| `acceptance` | Clean committed tip, `check`, `build`, `properties`, `infra-check`, the full suite with coverage including live tests, then the clean tip again |

`acceptance` runs no affected-unit stage before its full suite.

`CVETA2_TEST_WORKERS` (default `2`) sets the xdist worker count. Before heavy work,
inspect the machine's reported load and choose it within the available headroom; there
is no shared heavy-job lock.

### Worktree-local state

Each worktree owns its environment, testmon history, coverage output and mutable Ruff,
mypy and pytest caches. Never share verification results across worktrees. Do not edit
files in a worktree while verification runs in it.

`scripts/testmon_environment.py` computes the testmon environment fingerprint that `test`
and `test-full` pass as `--testmon-env`. It covers what testmon cannot track: the
interpreter, the locked dependencies and verification configuration, static test and
package assets, the complete relative membership of source and test files, and the
content of `scripts/` and of pytest startup code (every `conftest.py` and each `-p`
plugin of the pytest `addopts`). An unseen fingerprint needs a full baseline; returning
to unchanged, previously verified inputs may reuse the matching history. Selection by
Python content stays testmon's job: changed Python behavior selects the affected tests,
and failed tests run again on the next attempt. When an input class cannot be reliably represented,
run `test-full`. A deselected test is not a freshly executed test; report the actual
selection.

### Hooks and staging guard

`bash scripts/install-hooks.sh` installs `pre-commit` and `commit-msg` dispatchers. It
saves a foreign or absent previous installation for rollback, and makes no backup when
the installed hooks are already current. The dispatcher resolves the invoking worktree
and refuses to run when `Taskfile.yml` or `scripts/git-hook.sh` is missing there; such a
checkout cannot commit through the hooks. prek runs the hooks with that worktree's
configuration.

Before prek can stash anything, `scripts/git-hook.sh` rejects a commit with unstaged
tracked changes or nonignored untracked files. It never stages, deletes or stashes.
Mandatory guards live in these executable scripts, not in Task preconditions a caller
can bypass.

- `pre-commit` runs `verify` once, serially, on every commit. A passing run prints
  testmon's file comparison, the number of selected tests and pytest's result counts,
  and keeps the full output in the ignored `.cache/verify-last.log`. Report the
  selection from those lines; testmon omits unaffected tests without counting them. The
  log is informational and never establishes completion.
- `commit-msg` validates Conventional Commits with the types listed in
  [.pre-commit-config.yaml](../.pre-commit-config.yaml). `scripts/git-hook.sh` clears
  `SKIP` and `PREK_SKIP` for this stage, so they defer `pre-commit` hooks only.

There is no pre-push or manual hook stage; run other stages through Task. Rebase,
cherry-pick and merge run no pre-commit checks: verify the combined content.

### Check selection

Select checks per issue from the Verification section of the
[issue template](agents/issue-template.md), and record them in the Linear issue with the
base and tip SHAs. The base is the merge base of the task branch with `main`.

| Change | Selected checks |
| --- | --- |
| Any commit | Commit hook: staging guard, verify (static checks + affected unit tests), Conventional Commit message |
| PR whose commits bump the version (feat, fix, perf, breaking) | acceptance on the clean committed tip |
| Non-bumping change to cveta2/adapters/{cvat,s3,clearml}, fetch/upload/managed orchestration, tests/integration/, its Kubernetes manifests, or dependencies | integration (preflight + live tests) |
| Changed functions under cveta2/ | Mutation report (mutation -- --base main) |
| pyproject.toml build settings or sdist contents, or adding, removing or renaming a file the sdist ships (README.md, CHANGELOG.md, GLOSSARY.md) | build |
| Property tests or Hypothesis settings | properties |
| Inputs that testmon selection cannot represent | test-full |
| Behavior, interface, dependency, security or operational-policy change | Fresh independent review after integrated verification |
| Documentation and instructions only | Commit hook only |

The version bump follows the [commit types](#commit-procedure). A documentation-only
change touches no product code, test, script, dependency or executable configuration;
`pyproject.toml`, `Taskfile.yml`, `.pre-commit-config.yaml`, presets and skill scripts are
not documentation. `acceptance` already includes `build`. Where boundaries a change
affects lack enforcement, see [architecture](architecture.md#enforcement).

### Order, reuse and reporting

1. Start with focused product tests where useful.
2. Run `fix`, inspect its fixes and formatting, and stage only task-owned inputs.
3. Commit; the hook runs `verify`. The final committed content needs a successful
   `verify` with `SKIP` cleared: reuse an applicable passing hook run instead of
   repeating it, and after an explicitly deferred intermediate commit run `verify` once
   the final content is ready.
4. Run the selected mutation report, then the other selected stages. Run `acceptance`
   on the clean committed tip, without an equivalent affected-unit run before it.
5. After integrating parallel work, verify the combined branch.

Reuse a successful check only while its inputs remain unchanged; rerun the checks that
changed inputs affect. A live acceptance result is reusable only within the same
acceptance attempt on the unchanged clean tip. Property exploration, mutation,
preflight, live checks and release operations are never cached.

The status vocabulary and waivers follow [AGENTS.md](../AGENTS.md). Until a waiver
exists, report a PR with a gate not run as not merge-ready. Missing or failing required
checks remain acceptance gaps.

Report what actually ran and what was selected. Keep passed checks, actual failures,
deferred checks and incomplete cleanup distinct. An interruption is not success. A
failure caused by unrelated existing work is a reported blocker, not permission to change
or discard that work. Report the commit, the checks, the mutation outcome, the remaining
worktree state and any pushed ref confirmed remotely. What the evidence covers is listed
in the [issue tracker](agents/issue-tracker.md#evidence).

Review documentation consistency proportionately within the issue and PR; there is no
documentation checker.

### Deferral of live checks

A live check is deferred when it could not run because infrastructure is temporarily
unavailable: the cluster does not answer, the node cannot admit the session quota, a
timeout, or session services not ready (or not seeded) within their deadlines, which is
blocked setup.

`infra-check` is read-only, creates nothing and is bounded overall by
`CVETA2_INFRA_CHECK_TIMEOUT` (60 seconds by default):

| Outcome | Exit | Meaning and action |
| --- | --- | --- |
| AVAILABLE | 0 | Live verification may start; setup rechecks availability |
| UNAVAILABLE | 3 | The cluster does not answer, the node cannot admit the quota, or the deadline expired: defer the live checks |
| ERROR | 1 | A missing tool or context, a refused namespace permission or an unexpected failure: diagnose it, never wait on it |

Recheck availability before every live run. Task-driven availability waiting stays
bounded; explicitly requested operator waiting is separate (see the
`running-integration-tests` skill). Readiness, seeding and teardown keep their own
timeouts; the preflight deadline is not a deadline for the whole live suite.

When infrastructure is unavailable:

- Report the reason and the deferred checks, and keep them visibly incomplete in the
  Linear issue.
- Continue independent implementation, documentation, review and local checks, and
  repair ordinary code failures within scope.
- Retry at a meaningful verification milestone or after evidence that availability is
  restored, without polling.
- When only blocked verification remains, stop and ask for the user's decision.

Loss of availability during setup is blocked setup; an assertion failure is a test
failure. A successful preflight without executed live tests is not acceptance.

### Mutation report

`scripts/mutation.py` maps the staged diff to the top-level `cveta2/` functions and
methods it touches, exports the index into a fresh temporary workspace and runs mutmut
there on those functions only. It never runs in a hook and caches nothing between runs.
Its docstring describes the mechanics.

```bash
uv run --locked task --exit-code mutation                              # staged change vs HEAD
uv run --locked task --exit-code mutation -- --base main               # staged tree vs merge base with main
uv run --locked task --exit-code mutation -- cveta2/domain/merge.py    # every function of a file
uv run --locked task --exit-code mutation -- --keep --strict           # keep workspace; survivors fail
uv run --locked task --exit-code mutation -- --budget-seconds 0 --max-functions 0  # no limits
```

The selected report uses `--base main`; the default compares staged content with `HEAD`
only, so do not mistake one for the other. With `--keep`, `cd` into the printed workspace
and use `<repo>/.venv/bin/mutmut show <name>` or `browse`.

The budget is at most 8 changed functions (`--max-functions`) and 120 seconds of mutmut
(`--budget-seconds`). Unjudged mutants count as "not run" and mutants no unit test
reaches as "not reached by tests", never as survivors. A run that judges no mutant before
the budget expires reports "no verdict" and fails; rerun it with a larger
`--budget-seconds`.

| Exit | Meaning |
| --- | --- |
| 0 | Report produced; survivors are printed (the first five with diffs) and are advisory. Also: nothing to mutate, or no unit test calls the changed functions |
| 1 | Under `--strict`: survivors or uncovered functions remain |
| 2 | Tool, configuration or clean-test failure, or "no verdict" (rerun with a larger `--budget-seconds`); never a result |

Survivors are information, not a gate; tool errors and failing clean tests remain
unresolved. The `mutation-testing` skill owns survivor triage.

mutmut mutates only code inside undecorated top-level functions and methods (one bare
`@staticmethod` or `@classmethod` is allowed), never f-strings, module constants or
docstrings, and skips lines matching `do_not_mutate_patterns`. "No mutants" passes. "No
unit test exercises the changed functions" (code that only `tests/integration` reaches)
passes too, but prompts a unit test.

`[tool.mutmut]` in [pyproject.toml](../pyproject.toml) keeps these invariants:

- `pytest_add_cli_args` keeps `-n 0` (mutmut forks per mutant; xdist would start a pool
  each time) and the `--ignore` list of suites that never execute package code.
- `mutate_only_covered_lines` stays off; its coverage pass breaks the numpy import.
- `only_mutate` is never set: the script derives it and refuses a checked-in one.
- `do_not_mutate_patterns` holds stable presentation surfaces (logging, progress bars,
  argparse help), never logic.

## Test conventions

- Tests observe behavior a caller can see, never third-party tooling or source wording.
- Extend existing modules and reuse `tests/fixtures/` and `tests/helpers.py`. Prefer
  parametrization or properties for related cases.
- Assert presentation only where it is a public CLI contract. Never add a test only to
  kill a mutant of a default argument, a message's wording or another presentation
  detail, and never reshape correct production code only to stop a mutant. Do not pin
  message wording, or serialized formatting that a consumer parses anyway.
- Hypothesis profiles live in `tests/conftest.py`: the default `cveta2` profile is
  deterministic, and `explore` (the `properties` stage) randomizes. The ignored
  `.hypothesis/` database replays failures. Run `properties` after changing a property
  and when it is selected.
- For targeted unit pytest commands, exclude `tests/integration` by directory.
- pytest-randomly prints its seed; reproduce with `--randomly-seed=<seed>` or disable it
  with `-p no:randomly` when appropriate.

### Test configuration isolation

Tests never read or write a developer's real configuration or cache. Preserve these
guards:

- `tests.env_isolation`, loaded through `-p` in the pytest `addopts`, redirects `HOME`
  and the XDG directories before `cveta2` is imported.
- The autouse fixtures in `tests/conftest.py` give each test its own config path and
  cache directory, disable the annotation cache unless a test opts in, and reset worker
  counts.
- The same conftest hides the live session's variables, listed in `CVETA2_LIVE_EXPORTED`,
  from unit tests; `scripts/mutation.py` passes none of them to mutmut.

## Live tests

The live tests are the pytest tests under `tests/integration`. `tests/conftest.py` marks
them `integration` and puts them in the `live` xdist group, so under `--dist loadgroup`
one worker runs them serially while unit tests stay parallel. Keep `--dist loadgroup`
and never split the `live` group across workers: each worker would start its own
session. Run them through the `running-integration-tests` skill. The session tool and its
interfaces are described in the module docstring of
[tests/integration/lifecycle.py](../tests/integration/lifecycle.py).

These rules always apply:

- **Own namespace.** Each live session deploys its own CVAT, MinIO and ClearML into one
  namespace it creates in the `docker-desktop` cluster, `cveta2-it-<id>`, and deletes
  that namespace by exact name on success, failure and interruption, on every branch
  including `main`, unless `INTEGRATION_KEEP_DATA=1`. The lifecycle tool, not cluster permissions, enforces the
  prefix.
- **Never touch others.** Never act on a namespace this session did not create: not
  another session's, not another project's, not a platform namespace.
- **No shared services.** Use no shared stand or service and no helper from another
  repository; the cluster's dedicated ClearML and FiftyOne MongoDB are not for tests.
- **No GPU.** No workload requests `nvidia.com/gpu`.
- **Never restart Docker Desktop**, and never change cluster settings, to make a
  verification gate pass.
- **No dependence on earlier sessions.** The platform may delete any project namespace 48
  hours after creation or after a cluster restart. A session finishes well inside that
  lifetime, never relies on data from an earlier one, and a vanished namespace needs no
  repair.
- **Credentials.** Each session generates its own credentials. They exist only in the
  namespace's Secrets and the test process environment, and are never printed, logged or
  written to a tracked file.
- **Concurrency.** Sessions from several worktrees or agents may run at once; each owns
  its namespace, local ports and credentials and shares none. The node is the only shared
  limit, and preflight checks that it can admit one more session quota. There is no
  project-wide run cap.

The manifests in `tests/integration/k8s/` are plain Kubernetes manifests applied with
`kubectl`; Helm is not used. They keep these properties:

- `quota.yaml` holds the session's `ResourceQuota` and `LimitRange`, created before any
  workload. Every container declares requests and limits that fit the quota. The sizes
  are the project's own choice: change them there, never by removing the quota.
- Disposable data uses `emptyDir`. A claim exists only where several pods share data (the
  CVAT data directory) and names `storageClassName: hostpath`; nothing references
  `local-path` or `/mnt/wsl/data/k8s-volumes`.
- The host reaches services only through loopback `kubectl port-forward`, over plain
  HTTP. No Ingress, NodePort or host port, and no certificate to trust.
- Image tags stay pinned. The CVAT server stays on its verified version; changing that
  version is a separate change.
- CVAT includes the chunks worker and every other component the live suite needs, and
  nothing it does not (frontend, analytics, serverless functions, unused queues).
  ClearML provides its API server, file server and stores, with no web UI, agent or
  async-delete service.

## Commit procedure

1. Inspect `git status --short`, the relevant diff and the staged diff, under the
   working-tree rule in [AGENTS.md](../AGENTS.md).
2. Stage exact task-owned paths (`git add -- <path>`), never broadly, and inspect the
   staged diff.
3. Write a Conventional Commit message, `type(scope)!: description`, with a lowercase
   type from the `conventional-pre-commit` arguments in
   [.pre-commit-config.yaml](../.pre-commit-config.yaml). When several writers share the
   checkout, use a unique temporary message file.
4. Commit. Intermediate task commits may defer development verification explicitly with
   `SKIP=verify`; clear `SKIP` before final verification. Commit automatic formatting
   and other mechanical fixes separately, then rerun the checks their inputs affect.

The commit type decides the release:

- `feat`, `fix` and `perf` bump the version, and so does `!`; a `!` needs a
  `BREAKING CHANGE:` footer for the changelog text.
- A `BREAKING CHANGE:` footer in any commit bumps too, including one in a commit listed
  inside a squash-merge body. While the version is 0.x a breaking change bumps the minor.
- Other types do not bump. Intentional lockfile-only updates use `build(deps):`.
- Reword git's default `Revert "..."` subject into a typed header.

## Releases

A human merge of a PR into `main` is the only release trigger and its authorization.
There is no release PR and no local release step. Because the conventional parser also reads
the commit messages listed in a squash-merge body (any body paragraph that starts like a
Conventional Commit header), check the PR title and the commits it squashes before the
merge.

[release.yml](../.github/workflows/release.yml) runs on `pull_request_target` `closed`
events only for PRs merged into `main`. One concurrency group, `release-main`, serializes
the runs and never cancels a running one; closely spaced merges may share one release.
Only the release job has `contents: write`. It checks out `main` with full history and
tags, installs the pinned python-semantic-release and runs
`semantic-release version --no-vcs-release`, configured by `[tool.semantic_release]` in
[pyproject.toml](../pyproject.toml). The job runs no verification and establishes no
test, live or packaging outcome.

What a release changes: the package version is dynamic, read by hatchling from
`__version__` in `cveta2/__init__.py`, so `pyproject.toml` and `uv.lock` hold no version
and the release runs no build command. When a release is due, semantic-release updates
`__version__` and `CHANGELOG.md` only (mode `update` inserts the new release and leaves
existing entries as written), commits `chore(release): <version>`, creates the annotated
`v<version>` tag, pushes `main` and then pushes the tag. When no release is due it
changes nothing.

What a release publishes: that commit and its annotated tag, nothing else. Never a GitHub
Release, asset or package. It never merges or rewrites history.

semantic-release is not in the development environment. For a dry run, install it ad
hoc: `uvx --from python-semantic-release==10.7.0 semantic-release --noop version`.

After a merge, record on the Linear issue the release run URL, the source and released
SHAs, the version or "No new version" result and the tag identity
(`git ls-remote origin refs/heads/main 'refs/tags/v*'`).

### Recovery states

semantic-release pushes `main` first and the tag second, as two separate pushes, and
before pushing checks that remote `main` still equals the commit it released from. Read
the run log and the remote refs before deciding which state applies.

- **Failed before any push** (a configuration error, a moved `main`, a rejected branch
  push): nothing is published. The next merge releases everything still unreleased, or a
  human reruns the workflow on the current `main` (`gh run rerun <run-id>`). A
  configuration error repeats on every merge; fix it through a PR.
- **Release commit on `main` without its tag**: stop and report. Nothing more is merged
  until a human has pushed the tag for that release commit. A human rerun with nothing
  merged in between computes the same version, finds `cveta2/__init__.py` and
  `CHANGELOG.md` already current, makes no commit, tags the current `HEAD` and pushes only
  the tag. Merging first goes wrong: after a `fix` merge the run tags the newer `HEAD`
  with the same version, so the tagged version contains a fix its changelog block does
  not list; after a `feat` or breaking merge the next version is higher, the first is
  never tagged, and the new block probably repeats the untagged version's entries
  (derived by reading the source, not observed).
- **Tag for the computed version already exists**: semantic-release prints
  `No release will be made, <version> has already been released!` and exits 0 without a
  commit, tag or push. The run is green although nothing was released, so the run log,
  not the run status, shows whether a release happened. If that tag is not on `main`,
  every run computing the same version skips the same way until a human investigates and
  removes it.
- **Branch protection or repository rules reject the bot's push**: report that the release
  needs a bypass for the Actions token; never weaken human protections. Protection on
  `main` without that bypass blocks every release push.

### Never

- Push `main`, merge locally into `main`, or create, push, move or delete a tag.
- Run `semantic-release` in a mode that writes; `--noop` dry runs are fine. Nothing
  technical stops a local `semantic-release version` from pushing; this rule is policy,
  not enforcement.
- Force-push, rewrite history or reset unrelated work.
- Publish a GitHub Release, release asset or package.

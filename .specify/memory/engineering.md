# cveta2 engineering guidance

Contents: [Project](#project) · [Preserve the working tree](#preserve-the-working-tree) ·
[Spec Kit development workflow](#spec-kit-development-workflow) · [Architecture](#architecture) ·
[Code conventions](#code-conventions) · [Verification](#verification) ·
[Documentation](#documentation) · [Mutation testing](#mutation-testing) ·
[Integration tests](#integration-tests) · [Shared infra](#shared-infra) ·
[Configuration](#configuration) · [Commits, hooks, and releases](#commits-hooks-and-releases)

## Project

cveta2 is a Python >=3.12,<3.14 CLI and API for CVAT annotation projects. It fetches
bounding-box annotations, partitions them by task completion state, downloads
images from S3, uploads datasets, and manages project labels. Run Python tools
through `uv run`.

Language rules live in [AGENTS.md](../../AGENTS.md). This file owns detailed
operational guidance; [constitution.md](constitution.md) owns governance.
Read [architecture.md](architecture.md) for module ownership and
[the dataset contract](../../docs/dataset-contract.md)
for output-format behavior.

## Preserve the working tree

Before editing, inspect `git status --short`, the relevant diff, and the staged
diff. Treat existing modifications and untracked files as user work. Do not
stash, reset, broadly stage, commit, or push them. Stage and commit only exact
task-owned paths when authorized, following
[Commits, hooks, and releases](#commits-hooks-and-releases). Local task-owned commits may be autonomous. Pushes require separate authorization;
existing session authorization remains valid within scope. Explicit stopping points apply.

## Spec Kit development workflow

Spec Kit is the primary specification, planning, and task workflow for new or
changed capabilities. Bug fixes and refactors that change no capability contract
use the lightweight path below instead. Read [constitution.md](constitution.md) before
planning. Codex uses `$speckit-<step>`; Claude uses `/speckit-<step>`.
Discover the governing process from explicit user selection, these instructions
and active artifacts before invoking helpers. Record relevant Python contract and
verification evidence within the native stages.
Inspect current code, configuration, existing diffs and task evidence: artifacts
record intent, while implementation and executed checks establish behavior.

Both integrations are installed, with Codex as the default.

Set up a clone with `uv sync` and `uv run prek install` (one command
installs the pre-commit and commit-msg stages; prek is a pre-commit-compatible
runner that reads `.pre-commit-config.yaml`). Python 3.12 or 3.13 and uv are
required; the live tests in the full acceptance suite also need `kubectl` with the
`docker-desktop` context and the installed `k8s-infra` skill.

For a new capability, run `specify` to create `specs/<number>-<name>/spec.md`.
Continue through `clarify` -> `plan` -> `checklist` -> `tasks` -> `analyze` ->
`implement` -> `converge`. Invoke each skill separately and review its output.
A completion request carries authorized work through that sequence, documentation,
verification and the project release workflow without separate stage prompts.
Ask only for material missing decisions or authorization outside existing scope.
Explicit planning-only, review-only, no-commit/no-release and other stopping points
take precedence. Host Plan Mode/read-only permits inspection and proposed records
and checks, not persisted artifacts, implementation, mutating hooks or release.
Resolve ambiguous requirements, incomplete quality checklists, constitution
violations, and blocking analysis findings before implementation. The bundled
four-step `speckit` workflow runner does not include all repository-required
steps; do not use it as a substitute for this sequence.

The [baseline](../../specs/baseline.md) owns consolidated functional behavior and the
[dataset contract](../../docs/dataset-contract.md) its exact formats; retired decisions
and evidence are recoverable from the checkpoint named in the constitution, principle I. For a change to
a consolidated capability, create a feature describing the delta from the baseline.
For an existing active feature, select its directory, update `spec.md` and run the
remaining sequence. Reconcile the plan and task list with the revised spec and
update the baseline on acceptance; mark completed work only when verified. Keep acceptance
criteria and relevant verification commands in the artifacts. Record dated
check results and limitations with the feature, and repeat implementation and
convergence until no required work remains. Unrelated capabilities get separate
feature directories. Do not retroactively specify the whole application.

The active feature comes from ignored `.specify/feature.json` or the explicit
`SPECIFY_FEATURE_DIRECTORY` environment override, never the checked-out branch.
Set the override to a repository-relative `specs/<number>-<name>` path when
resuming a feature; confirm resolution with
`.specify/scripts/bash/check-prerequisites.sh --paths-only --json` before any
artifact-writing command. Create development branches manually; the optional
Git extension is not installed.

Documentation-only corrections use only native Spec Kit or OpenSpec documentation checks. Maintenance without
behavior changes may use a scoped maintenance plan under `docs/plans/<task>/`
(or, for a small change, its commit message), appropriate checks and applicable
review/release evaluation, without creating an application feature specification.
A bug fix still needs a failing observation, reproduction when feasible, and
verification of the original failure path. A fix that changes a documented
capability contract goes through Spec Kit.

Other skills may support implementation, debugging, review, and verification;
do not create a competing specification or plan under another workflow.
Existing hooks, targeted checks, mutation and integration contracts, and
commit/release authorization still apply. Spec Kit requirements are enforced
through repository guidance, without an additional CI or hook gate.

## Architecture

Reuse executable import contracts; add scoped coverage and a meaningful forbidden
dependency negative case where affected boundaries lack enforcement. Reconcile the
final diff with actual checks, documentation and applicable review. Missing or
failing required checks remain acceptance gaps.

The contracts in `pyproject.toml` enforce exhaustive inward layers:

```text
public facades → interfaces → composition → adapters → application → domain
                                         application.use_cases → client → ports → settings/results
```

Composition may also depend directly on inner layers to construct and inject
production dependencies. Domain owns pure policies and values. Application owns
typed ports and orchestration; it receives resolved settings/effects explicitly,
never discovers configuration or creates adapters. Incoming `interfaces/commands/`
own prompts, argument mapping and `sys.exit`; application workflows remain
prompt-free and raise `Cveta2Error`. The public API remains prompt-free.
Supported top-level modules are compatibility facades; canonical modules cannot
import them. Removed internal package paths are not compatibility promises.

CVAT/S3/config/ClearML adapter groups remain independent, using shared
file/execution adapters where needed. All `cvat_sdk` imports belong to
`adapters/cvat/`, `boto3`/`botocore` to `adapters/s3/`, ClearML to
`adapters/clearml/` and questionary to incoming interactive interfaces. Neutral
ports must not import implementations. Inner package imports do not eagerly load
infrastructure. Lexical paths and in-memory pandas are allowed inward; file IO,
configuration/environment discovery, network/SDK IO, clocks and thread/process
execution are external effects. Runners, clocks and locks are explicit
application dependencies. Execution preserves input order, cancels queued work
on uncaught failures and joins active work before propagating them.

Run `uv run lint-imports` and `uv run pytest tests/test_architecture.py` (which
also runs the effect-ownership checker in `tests/architecture_effects.py`) to
verify layers, module coverage, adapter independence, SDK/prompt ownership, facade exclusion, sibling acyclicity
and inner effect ownership, including local/type-only imports and aliases.
Negative acceptance fixtures exercise forbidden dependencies and effects.
Architecture acceptance reconciles the module record, task-owned diff,
verification and independent review.

Read [architecture.md](architecture.md) before changing layer flow, `ORG/PROJECT`
resolution or fetch/upload/convert behavior. CVAT retains shapes for deleted
frames, so `domain/partition.py` concatenates deletion records before annotation
records to win same-task ties. Recency uses `task_id`, never
`task_updated_date`, because label edits update that timestamp across tasks.

## Code conventions

- Use `loguru`, pydantic configuration/models, and f-strings.
- Catch specific exceptions. Never silently swallow a failure; use `warning`
  when the caller receives degraded or incomplete results.
- When a loop skips failed items, track and summarize the skipped items.
- Ruff `BLE001` rejects broad exception handlers; do not suppress it.
- Use dynamic attribute access only at opaque third-party SDK boundaries and
  explain why.

## Verification

Choose checks from the changed behavior:

```bash
uv run pytest tests/<relevant-test-file>.py
uv run pytest -k '<relevant expression>'
uv run ruff check <changed Python paths>
uv run mypy <changed package paths>
uv run lint-imports
uv run pytest
```

Use proportionate collaboration: independent bounded work is useful only when
ownership and dependencies justify it. Substantive changes need fresh independent
review after parent integration and verification; reuse the native final review
for Python and architecture criteria rather than introducing a competing review.
Small low-risk edits may use direct review and focused checks.

Start with the nearest meaningful tests and expand when shared behavior,
interfaces, or observed failures justify it. A documentation-only change needs
no package test run: its commit runs only ruff and the other fast hooks, because
the heavy hooks are filtered to code and dependency paths. A commit runs the
configured hooks, so do not duplicate the full gate before every small edit.

Keep the suite lean. A test MUST observe behavior a caller or user can see:
- do not add a test whose only purpose is to kill a mutant of a default
  argument, a log line or other presentation wording;
- assert message wording only for CLI contract output;
- extend the module's existing test file instead of creating a new file per
  origin (`*_regressions`, `*_architecture` for non-structural checks);
- parametrize near-identical cases, and prefer a Hypothesis property over a
  list of examples for round trips and invariants;
- reuse the shared fakes in `tests/fixtures/` and builders in `tests/helpers.py`
  instead of local copies.

Hypothesis runs with a fixed seed and 50 examples per property (profile
`cveta2` in `tests/conftest.py`), so commits are reproducible but every run
checks the same inputs. Explore with random inputs before a merge or after
changing a property:
`uv run prek run property-exploration --hook-stage manual --all-files`
(1000 random examples, about 20 s). A failure is stored in the ignored
`.hypothesis/` database and replayed by later runs.

Pytest normally uses xdist and loads `tests.env_isolation` during startup. That
plugin redirects HOME before imports; do not drop it when overriding
`addopts`. Autouse fixtures isolate config and task cache, reset transfer
workers before and after each test, and clean the temporary HOME at session
teardown. Preserve those yield/finally cleanup paths when editing fixtures.

An unfiltered pytest run includes the live tests under `tests/integration`.
The default prek unit hook excludes that directory and its conftest.
`tests/conftest.py` marks them `integration` and puts them in the `live` xdist
group, so `--dist loadgroup` (in `addopts`; keep it when overriding) runs them
serially on one worker while unit tests stay parallel. Exclude them with
`-m "not integration"` for quick local runs and in bounded subagent work.
pytest-randomly shuffles test order and prints the seed; reproduce an order
with `--randomly-seed=<seed>` and disable it with `-p no:randomly`. No
GPU-specific pytest marker is configured. Use the `running-integration-tests`
skill for live tests, the stopped-stand wait and lifecycle operations.

## Documentation

Update the Russian `README.md` and `docs/` when
CLI or public API behavior changes.
`docs/configuration.md` owns configuration details; `docs/cli.md` owns
commands and flags; `docs/images-and-cache.md` owns S3, cache, and ClearML
behavior. Maintain [architecture.md](architecture.md) and the
[living dataset contract](../../docs/dataset-contract.md)
when a feature changes their documented behavior. Keep dated findings in
feature evidence; retired findings stay at their checkpoint commits, such as the
[2026-09-04 review](https://github.com/BuckanovNikita/cveta2/blob/af0073e5bd8a8799f0cfd322cfb27c8efd7b747d/specs/001-project-documentation/evidence/bug-review-2026-09-04.md).

### Project skills

Project skills hold procedures for specific situations; rules that apply to every
task belong in this file. Authored skills live in `.agents/skills/<name>/`, and
`.claude/skills/<name>` is a relative symlink to that directory
(`../../.agents/skills/<name>`), so both hosts read one copy. Add each new
authored skill to the `.agents/skills` exceptions in `.gitignore`.

The `speckit-*` skills are the exception. They are generator-owned host variants:
each copy carries its host's invocation sigil (`/` for Claude, `$` for Codex), and
the Claude copy carries Claude-only frontmatter. Their hashes are recorded in
`.specify/integrations/{claude,codex}.manifest.json`. Never symlink or hand-edit
them. Regenerate them with `specify` (see `.specify/integration.json` for the
installed integrations).

## Mutation testing

`scripts/mutation.py` mutates the functions a commit changes, in a fresh
workspace exported from the index, and reports survivors without failing (the
manual `mutmut` hook), within a budget of 8 functions and 120 s per commit.
Survivors are information: triage behavioural ones and never add a test whose
only purpose is to kill a mutant of a default argument or of wording. Nothing
is cached between runs. Read the
`mutation-testing` skill before triaging survivors or changing the
`[tool.mutmut]` settings.

## Integration tests

Live tests run against the shared CVAT, MinIO and ClearML stands of the
docker-desktop cluster under one run tag per pytest session; nothing runs on this
host. The `running-integration-tests` skill owns the session fixture and
lifecycle tool, the tag (minted through the k8s-infra skill, adopted with
`INFRA_RUN_TAG`), the credentials (evaluated from the project Secrets, never
stored), serial execution and exact-tag cleanup. Do not start, stop, or clean a
stand manually, and never act on another run's tag.

The owner stops the stands at times. A stopped stand makes the session print a
notice and wait until the stands answer again (`CVETA2_STAND_WAIT_TIMEOUT`
bounds the wait); it is not a failure. Run a command that may wait in the
background, tell the user it waits for the stands, and never restart a stand,
skip the live tests or bypass the hook because of it.

## Shared infra

Use the installed global `k8s-infra` skill and read its
`references/run-contract.md` before touching a stand. Its maintained registry
owns project identities, allowed stands, capacity limits, helper locations,
credential lookup, and machine setup; do not duplicate those values here.
This project's lifecycle tool, `tests/integration/lifecycle.py`, acts as `cveta2`
and resolves the installed skill.

- Preflight with the skill's `infra.py room`; obey WAIT (exit status 3).
- Mint one owned tag through `infra.py newtag --project cveta2 --slug <what>`.
  Assign, then export `INFRA_RUN_TAG` only after a successful mint. Export
  `INFRA_HARNESS=codex|ci|human` before minting outside Claude Code.
- Name every created object with that tag. Read credentials from the skill's
  project environment helpers, never from files or logged output.
- Run and clean integration resources through the `running-integration-tests`
  skill and the repository lifecycle tool, on success and failure. Prove cleanup
  with the exact-tag listings; CVAT cloud storage is part of that cleanup.
- Never broaden a cleanup selector beyond the exact run tag.
- Read current capacity from the registry; never infer permission from an idle
  stand. Never run `cleanup --stale` without `--dry-run`.
- Never touch another tag or an unrelated durable name. Report anything
  intentionally kept by its full name.

## Configuration

`CvatConfig.load()` resolves environment variables, then
`~/.config/cveta2/config.yaml` (or `CVETA2_CONFIG`), then
`cveta2/presets/default.yaml`. See `docs/configuration.md` for supported
fields and one-run overrides. Tests isolate these paths; never let tests read or
write a developer's real configuration.

## Commits, hooks, and releases

### Commits

Stage exact task-owned paths (`git add -- <path>`). Messages are Conventional
Commits, `type(scope)!: description`, with a lowercase type from the
`conventional-pre-commit` args in `.pre-commit-config.yaml` (the commit-msg hook
enforces them). Only `feat`, `fix`, `perf` and `!` move the version; a `!` needs a
`BREAKING CHANGE:` footer for the changelog text. Reword git's default
`Revert "..."` subject into a type. Use a unique temporary message file when
several writers share the checkout.

### Hooks

`uv run prek install` installs the pre-commit and commit-msg stages. Read
`.pre-commit-config.yaml` for the current hook set and each hook's path filter.
Hooks call `uv run --locked`, so a stale `uv.lock` fails rather than re-locks.
`uv.lock` may change only together with `pyproject.toml` (the `lockfile-guard`
hook); a deliberate re-lock alone, such as a dependency upgrade, is a
`build(deps):` commit made with `SKIP=lockfile-guard`, an explicit dependency-maintenance exception. Intermediate task commits may also
skip named verification hooks; commit-message checks remain enabled. Clear SKIP
and run the full default pipeline after the last task commit.

- Default verification runs unit checks at commit time; live integration and
  advisory mutation are manual hooks. There is no pre-push stage. Pushes still
  require separate authorization and the acceptance checks below.
- A hook that rewrites files (`uv lock`, `ruff format`): inspect the new diff,
  restage only task-owned paths and commit again.
- The `mypy` hook runs standalone whole-project analysis without stopping or
  modifying pre-existing daemon processes.
- The `pytest` hook runs affected unit tests and excludes `tests/integration`,
  including its conftest. Selected non-Python inputs and deletions run all unit tests because
  testmon tracks Python only. Coverage remains an explicit full-suite merge gate.
- Invoke `integration-tests` with `--hook-stage manual --all-files` for the live
  suite. It may wait for stopped stands; the `running-integration-tests` skill
  owns prerequisites, run tags and cleanup.
- Invoke `acceptance-tests` with `--hook-stage manual --all-files` for the full
  suite with coverage, including live tests, on the branch tip before merging.
- Invoke `mutmut` with `--hook-stage manual --all-files` for the staged change's
  advisory mutation report. Before accepting code changes, run it explicitly;
  for an unstaged branch tip use the mutation skill's branch comparison. Survivors
  remain advisory, while tool errors and failing clean tests must be resolved.
- A failure caused by unrelated pre-existing work: report the exact blocker; do
  not modify, stage or discard that work.
- Rebase, cherry-pick and merge run no pre-commit hook, while deletion-only commits select the relevant project-wide hooks. After rewriting history and before
  pushing it, run `uv run prek run --all-files`, and
  `uv run python scripts/mutation.py --base <upstream>` for the mutation report
  (the hook only sees staged changes, which are empty then).

Report the commit hash and subject, the pushed ref confirmed with
`git ls-remote origin <ref>`, the hooks that ran, the mutation survivors reported
and the remaining unrelated working-tree state.

### Releases

`main` changes only by a fast-forward merge (`git merge --ff-only`) of a branch
rebased onto it, after the full suite passed on that exact tip:
`uv run prek run --all-files` and
`uv run prek run acceptance-tests --hook-stage manual --all-files` (live tests
included, coverage enforced). The `main` tip is then a checked commit, so the release
commit, which only bumps the version, `CHANGELOG.md` and `uv.lock`, runs with
`SKIP=lint-imports,mypy,vulture,pytest` - the second standing hook exception;
ruff, `uv lock --check`, the lockfile guard, deptry and `uv build` still run. One
release at a time: the `release` skill holds a `flock` on
`.git/cveta2-release.lock` from the merge to the push.

On `main`, semantic-release derives versions, tags, and `CHANGELOG.md`; never
hand-edit the project version. Release right after the merge with the `release`
skill, which holds the commands and the recovery from a failed release hook.
Documentation-only changes still evaluate release but may produce no new version
tag.

Complete commits and releases after required checks under the authorization rules
in [Preserve the working tree](#preserve-the-working-tree). Pushes require separate authorization, including existing session authorization; it does not
authorize changing remotes, deployment or expanding scope. Publish Git version
tags only: no GitHub Release objects, release assets or registry publication
without an explicit user override. Report failed/unavailable gates as gaps; never
bypass them to force completion.

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
[the dataset contract](../../specs/baseline.md)
for output-format behavior.

## Preserve the working tree

Before editing, inspect `git status --short`, the relevant diff, and the staged
diff. Treat existing modifications and untracked files as user work. Do not
stash, reset, broadly stage, commit, or push them. Stage and commit only exact
task-owned paths when authorized, following
[Commits, hooks, and releases](#commits-hooks-and-releases). Standing user
authorization for completion includes required commits, release evaluation and
commit/tag pushes after applicable gates pass; do not request authorization
again within scope. Explicit no-commit/no-release or other stopping points override
it. A commit-only request without push authorization still stops before pushing.

## Spec Kit development workflow

Spec Kit is the primary specification, planning, and task workflow for behavior
changes, including bug fixes. Read [constitution.md](constitution.md) before
planning. Codex uses `$speckit-<step>`; Claude uses `/speckit-<step>`.
Discover the governing process from explicit user selection, these instructions
and active artifacts before invoking helpers. This project retains Spec Kit; the
shared `python-project-workflow` skill adds Python contract, checks, documentation
and packaging evidence inside its native stages, not another lifecycle. Use the
shared `module-architecture-planning` skill for the architecture gates below.
If either required shared skill is unavailable, report the missing gate and
continue independent inspection; do not invent its rules or claim acceptance.
Inspect current code, configuration, existing diffs and task evidence: artifacts
record intent, while implementation and executed checks establish behavior.

Both integrations are installed, with Codex as the default.

Set up a clone with `uv sync` and `uv run pre-commit install` (one command
installs the pre-commit and commit-msg stages). Python 3.12 or 3.13 and uv are
required; integration tests also need `kubectl` with the `docker-desktop`
context and the `k8s-infra` skill, whose presence arms the live gate.

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

The [baseline](../../specs/baseline.md) owns consolidated product/data contracts;
its immutable sources preserve historical decisions and evidence. For a change to
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

Documentation-only corrections and maintenance without behavior changes may
use the existing lightweight workflow: a scoped maintenance plan and adjacent
architecture record under `docs/plans/<task>/`, appropriate checks and applicable
review/release evaluation, without creating an application feature specification.
Runtime maintenance uses module impact and behavioral checks; only inspected
documentation-only work uses no-impact reasoning. A behavior-changing bug fix needs a
failing observation, reproduction when feasible, and verification of the
original failure path in its Spec Kit artifacts.

Other skills may support implementation, debugging, review, and verification;
do not create a competing specification or plan under another workflow.
Existing hooks, targeted checks, mutation and integration contracts, and
commit/release authorization still apply. Spec Kit requirements are enforced
through repository guidance, without an additional CI or hook gate.

## Architecture

Before implementation, record affected module responsibilities, interfaces,
allowed/forbidden dependencies and effect ownership in the native `plan.md`, with
an adjacent task-owned `architecture.json` and dependent checks in `tasks.md`.
Reuse executable import contracts; add scoped coverage and a meaningful forbidden
dependency negative case where affected boundaries lack enforcement. Validate the
record with the shared skill's validator using `--phase plan` and this repository
as `--repo-root` before implementation. Documentation-only work records inspected
no-impact reasoning and documentation checks; it does not need unrelated runtime
suites. Missing, unavailable or failing required documentation/architecture
checks remain acceptance gaps, not passing verification. Before acceptance
reconcile the complete task-owned diff, actual checks,
documentation and applicable review; validate with `--phase acceptance`.

For resumed work, compare current implementation with existing records and append
missing architecture/check/documentation tasks and amendments without rewriting
completed history. Do not bulk retrofit inactive feature records. Shared skills
add evidence to native artifacts; do not edit installed Spec Kit skills/templates.

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
interfaces, or observed failures justify it. A documentation-only change
normally needs `uv run pytest tests/test_docs.py`, not the entire code suite.
A commit runs the configured pre-commit hooks, so do not duplicate the full gate
before every small edit.

Pytest normally uses xdist and loads `tests.env_isolation` during startup. That
plugin redirects HOME before imports; do not drop it when overriding
`addopts`. Autouse fixtures isolate config and task cache, reset transfer
workers before and after each test, and clean the temporary HOME at session
teardown. Preserve those yield/finally cleanup paths when editing fixtures.

The only registered live-test marker is `integration`. Integration collection
is enabled by `CVAT_INTEGRATION_HOST`; integration runs must disable xdist to
avoid CVAT rate limiting. No GPU-specific pytest marker is configured. Use the
`running-integration-tests` skill for live tests and lifecycle operations.

## Documentation

`tests/test_docs.py` checks documented signatures, commands, flags, environment
variables, config fields, and relative links/anchors. Update the Russian
`README.md` and `docs/` when CLI or public API behavior changes.
`docs/configuration.md` owns configuration details; `docs/cli.md` owns
commands and flags; `docs/images-and-cache.md` owns S3, cache, and ClearML
behavior. Maintain [architecture.md](architecture.md) and the
[living dataset contract](../../specs/baseline.md)
when a feature changes their documented behavior. Keep dated findings in
feature evidence or immutable archive sources, including the preserved
[2026-09-04 review](https://github.com/BuckanovNikita/cveta2/blob/af0073e5bd8a8799f0cfd322cfb27c8efd7b747d/specs/001-project-documentation/evidence/bug-review-2026-09-04.md).
Documentation checks also cover Spec Kit memory and feature Markdown; upstream
template examples are excluded.

### Project skills

Project skills hold procedures for specific situations; rules that apply to every
task belong in this file. Authored skills live in `.agents/skills/<name>/`, and
`.claude/skills/<name>` is a relative symlink to that directory
(`../../.agents/skills/<name>`), so both hosts read one copy. Add each new
authored skill to the `.agents/skills` exceptions in `.gitignore`.
`tests/test_docs.py` enforces this layout and the manifest hashes below.

The `speckit-*` skills are the exception. They are generator-owned host variants:
each copy carries its host's invocation sigil (`/` for Claude, `$` for Codex), and
the Claude copy carries Claude-only frontmatter. Their hashes are recorded in
`.specify/integrations/{claude,codex}.manifest.json`. Never symlink or hand-edit
them. Regenerate them with `specify` (see `.specify/integration.json` for the
installed integrations).

### Portable usage skill

The canonical portable `cveta2` skill lives in
[corp-skills/skills/cveta2](https://github.com/BuckanovNikita/corp-skills/tree/main/skills/cveta2).
It teaches tool usage; this repository owns implementation and public contracts.
Edit that source package, not an installed agent copy. Keep machine-specific setup
in global environment guidance.

During planning, inspect the skill for changes to commands, public API, configuration,
authentication, dataset/conversion formats, defaults, side effects or failure recovery.
Record affected skill/reference paths in the native plan and add update and validation
tasks dependent on implementation. Internal-only changes may record a concrete,
inspected no-change reason. This applies to fixes and resumed features as well as
new features; preserve completed history when adding tasks.

During the documentation stage, reconcile the skill with the final implementation
and current user guides. Update examples, prerequisites, warnings and evaluation
cases together. Verify documented flags/signatures and representative local examples;
validate frontmatter, packaged links, Markdown and discovery using
[corp-skills maintenance](https://github.com/BuckanovNikita/corp-skills/blob/main/MAINTENANCE.md).
Repository documentation tests do not validate this external package.

Before convergence/completion, record the inspected source version/commit, changed
skill paths, actual checks and remaining limitations in dated feature evidence.
Reference the companion corp-skills commit when committed. If its checkout or access
is unavailable, record the required update as an open documentation task; do not mark
the feature complete. Follow each repository's release policy within authorization;
do not overwrite unrelated edits or install updated skills as a side effect.

## Mutation testing

`scripts/mutation.py` mutates the functions a commit changes, in a fresh
workspace exported from the index, and reports survivors without failing (the
pre-commit `mutmut` hook). Nothing is cached between runs. Read the
`mutation-testing` skill before triaging survivors or changing the
`[tool.mutmut]` settings.

## Integration tests

Live tests run against the shared CVAT, MinIO and ClearML stands of the
docker-desktop cluster under one run tag per run; nothing runs on this host.
The `running-integration-tests` skill owns the lifecycle tool, the tag
(minted through the k8s-infra skill, adopted with `INFRA_RUN_TAG`), the
credentials (evaluated from the project Secrets, never stored), serial pytest
execution, and exact-tag cleanup. Do not start, stop, or clean a stand
manually, and never act on another run's tag.

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

`uv run pre-commit install` installs the pre-commit and commit-msg stages. Read
`.pre-commit-config.yaml` for the current hook set. Do not bypass hooks unless the
user explicitly directs it.

- Every gate runs at commit time, so a passing commit is safe to push with plain
  `git push`; there is no pre-push stage.
- A hook that rewrites files (`uv lock`, `ruff format`): inspect the new diff,
  restage only task-owned paths and commit again.
- The changed-function mutation run and the live integration gate run last and
  only when their files change (`cveta2/`; for the live gate also
  `tests/integration/`, `pyproject.toml`, `uv.lock`). Mutation is advisory: it
  prints surviving mutants and passes, failing only on a tool error or a failing
  clean test run; triage
  behavioural survivors with the `mutation-testing` skill.
- The live gate runs for minutes while pre-commit keeps unstaged changes stashed:
  do not edit the checkout meanwhile. It replaces only objects named by its own
  run tag (on `main`, the durable `cveta2-main` slot); the
  `running-integration-tests` skill covers its failures. Skip it
  (`SKIP=integration-tests`) only on the user's request, as a one-commit bypass,
  never as a recovery step.
- A failure caused by unrelated pre-existing work: report the exact blocker; do
  not modify, stage or discard that work.
- Rebase, cherry-pick and merge run no pre-commit hook, and a commit that only
  deletes files runs no file-filtered hook. After rewriting history and before
  pushing it, run `uv run pre-commit run --all-files`, and
  `uv run python scripts/mutation.py --base <upstream>` for the mutation report
  (the hook only sees staged changes, which are empty then).

Report the commit hash and subject, the pushed ref confirmed with
`git ls-remote origin <ref>`, the hooks that ran, the mutation survivors reported
and the remaining unrelated working-tree state.

### Releases

`main` changes only by merge. On `main`, semantic-release derives versions,
tags, and `CHANGELOG.md`; never hand-edit the project version. Release right
after the merge with the `release` skill, which holds the commands and the
recovery from a failed release hook. Documentation-only changes still evaluate
release but may produce no new version tag.

Complete commits and releases after required checks under the authorization rules
in [Preserve the working tree](#preserve-the-working-tree). Standing
authorization covers the configured commit hooks and the push; it does not
authorize changing remotes, deployment or expanding scope. Publish Git version
tags only: no GitHub Release objects, release assets or registry publication
without an explicit user override. Report failed/unavailable gates as gaps; never
bypass them to force completion.

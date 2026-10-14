# cveta2 engineering guidance

## Project

cveta2 is a Python 3.10+ CLI and API for CVAT annotation projects. It fetches
bounding-box annotations, partitions them by task completion state, downloads
images from S3, uploads datasets, and manages project labels. Run Python tools
through `uv run`.

Follow the user's conversation language (English by default); repository language
conventions do not override it. User documentation and CLI output remain Russian.
Spec Kit memory, feature artifacts, and the dataset contract are English. This file owns detailed
operational guidance; [constitution.md](constitution.md) owns governance.
[AGENTS.md](../../AGENTS.md) is the discovery entry point and `CLAUDE.md` remains
its symlink. Read [architecture.md](architecture.md) for module ownership and
[the dataset contract](../../specs/001-project-documentation/contracts/dataset-format.md)
for output-format behavior.

## Preserve the working tree

Before editing, inspect `git status --short`, the relevant diff, and the staged
diff. Treat existing modifications and untracked files as user work. Do not
stash, reset, broadly stage, commit, or push them. Stage and commit only exact
task-owned paths when authorized; use the project `commit` skill for that
workflow. Standing user authorization for completion includes required commits,
release evaluation and commit/tag pushes after applicable gates pass. It satisfies
the commit and push request gates in that skill; do not request authorization
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

Both integrations are installed, with Codex as the default. See
[CONTRIBUTING.md](../../CONTRIBUTING.md) for setup and invocation examples.

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

Completed specifications are living contracts. For a change to an existing
capability, select its feature directory, update `spec.md` with the intended
behavior, and run the remaining sequence. Reconcile the plan and task list with
the revised spec; mark completed work only when verified. Keep acceptance
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
no-impact architecture record under `docs/plans/<task>/`, documentation checks
and applicable review/release evaluation, without creating an application feature
specification. A behavior-changing bug fix needs a
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

Run `uv run lint-imports`, `uv run python scripts/check_architecture.py` and
`uv run pytest tests/test_architecture.py` to verify layers, module coverage,
adapter independence, SDK/prompt ownership, facade exclusion, sibling acyclicity
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
[living dataset contract](../../specs/001-project-documentation/contracts/dataset-format.md)
when a feature changes their documented behavior. Keep dated findings in
feature evidence, including the preserved
[2026-09-04 review](../../specs/001-project-documentation/evidence/bug-review-2026-09-04.md).
Documentation checks also cover Spec Kit memory and feature Markdown; upstream
template examples are excluded.

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

`scripts/mutation_test.sh` gates the current `[tool.mutmut].only_mutate`
scope. Read the `mutation-testing` skill before changing scope, profiles,
equivalent-mutant entries, or triaging survivors. Scope is a ratchet: add a
module only with the tests and justified equivalents needed for zero unexplained
survivors.

## Integration tests

Live tests run against the shared CVAT, MinIO and ClearML stands of the
docker-desktop cluster under one run tag per run; nothing runs on this host.
The `running-integration-tests` skill owns the lifecycle scripts, the tag
(minted through the k8s-infra skill, adopted with `INFRA_RUN_TAG`), the
credentials (evaluated from the project Secrets, never stored), serial pytest
execution, and exact-tag cleanup. Do not start, stop, or clean a stand
manually, and never act on another run's tag.

## Shared infra

Use the installed global `k8s-infra` skill and read its
`references/run-contract.md` before touching a stand. Its maintained registry
owns project identities, allowed stands, capacity limits, helper locations,
credential lookup, and machine setup; do not duplicate those values here.
This project's lifecycle scripts act as `cveta2` and resolve the installed skill
through `scripts/integration_env.sh`.

- Preflight with the skill's `infra.py room`; obey WAIT (exit status 3).
- Mint one owned tag through `infra.py newtag --project cveta2 --slug <what>`.
  Assign, then export `INFRA_RUN_TAG` only after a successful mint. Export
  `INFRA_HARNESS=codex|ci|human` before minting outside Claude Code.
- Name every created object with that tag. Read credentials from the skill's
  project environment helpers, never from files or logged output.
- Run and clean integration resources through the `running-integration-tests`
  skill and repository lifecycle scripts, on success and failure. Prove cleanup
  with the exact-tag listings; CVAT cloud storage is part of that cleanup.
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

Use Conventional Commits. `uv run pre-commit install` installs pre-commit,
commit-msg, and pre-push stages. Read `.pre-commit-config.yaml` for the current
hook set. Do not bypass hooks unless the user explicitly directs it.

Pre-push runs the full mutation profile, version drift check, and the integration
gate when `tests/integration/.env` exists. The live gate replaces only objects
named by its own run tag (on `main`, the durable `cveta2-main` slot); the
integration skill defines that boundary.

`main` changes only by merge. On `main`, semantic-release derives versions,
tags, and `CHANGELOG.md`; never hand-edit the project version. Release commands
and commit semantics live in `CONTRIBUTING.md`. Complete that workflow within
existing user/standing authorization after required checks; documentation-only
changes still evaluate release but may produce no new version tag. Explicit
stopping points take precedence. Standing authorization satisfies project commit
skill request gates and covers the configured commit/push hooks; it does not
authorize changing remotes, deployment or expanding scope. Publish Git version
tags only: no GitHub Release objects, release assets or registry publication
without an explicit user override. Report failed/unavailable gates as gaps; never
bypass them to force completion.

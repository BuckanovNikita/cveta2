# cveta2 engineering guidance

Contents: [Project](#project) · [Preserve the working tree](#preserve-the-working-tree) ·
[Linear and GitHub workflow](#linear-and-github-workflow) · [Architecture](#architecture) ·
[Code conventions](#code-conventions) · [Verification](#verification) ·
[Documentation](#documentation) · [Mutation testing](#mutation-testing) ·
[Integration tests](#integration-tests) ·
[Configuration](#configuration) · [Commits, hooks, and releases](#commits-hooks-and-releases)

## Project

cveta2 is a Python >=3.12,<3.14 CLI and API for CVAT annotation projects. It fetches
bounding-box annotations, partitions them by task completion state, downloads
images from S3, uploads datasets, and manages project labels. Run Python tools
through `uv run`.

Language rules live in [AGENTS.md](../../AGENTS.md). This file owns detailed
operational guidance and engineering policy. The frozen Spec Kit constitution is historical provenance, not active workflow authority.
Read [architecture.md](architecture.md) for module ownership and
[the Linear contract index](contracts.md)
for output-format behavior.

## Preserve the working tree

Before editing, inspect `git status --short`, the relevant diff, and the staged
diff. Treat existing modifications and untracked files as user work. Do not
stash, reset, broadly stage, commit, or push them. Stage and commit only exact
task-owned paths when authorized, following
[Commits, hooks, and releases](#commits-hooks-and-releases). Local task-owned commits, task-branch pushes and GitHub PR creation are authorized by the project workflow; humans merge into `main`. Explicit stopping points apply.

## Linear and GitHub workflow

Follow [issue tracking and delivery](issue-tracker.md). Linear project documents own
current product requirements; issues own proposed changes, implementation plans,
acceptance criteria, dependencies and status. Repository guidance owns engineering
policy and executable configuration. Inspect source, diffs and dated evidence before
relying on historical task claims. Resolve material requirement ambiguities before
implementation. Supporting skills contribute within this workflow.

Spec Kit is temporarily disabled. Preserve `.specify/`, `specs/` and archived skills
unchanged; do not invoke their stages or update their artifacts. Explicit user
instruction is required to reactivate them. The migration branch follows the approved
replacement workflow; the repository-wide authority cutover occurs only after human
merge and satisfied migration acceptance criteria. Linear contract drafts remain
explicitly drafts until that cutover.

Set up each worktree with `uv sync --locked` and `bash scripts/install-hooks.sh`.
The installer preserves the previous installation and resolves the invoking worktree;
prek owns pre-commit and commit-msg execution using that worktree's configuration.
Live tests require kubectl and the configured local cluster context, and deploy their
own services without another repository, Helm, shared stands or CA installation.

Record outcomes, compatibility constraints, acceptance checks, implementation plans
where needed, and authorized stopping points in Linear. Bug fixes record the failing
observation, reproduction where feasible, and verification of the original failure path.
Compare the final diff, actual checks and independent review with acceptance criteria
before completion; continue authorized implementation, documentation and verification
without repeated stage prompts. Explicit session limits and host read-only modes take
precedence. Code release is suspended; an implementation request does not authorize it.

Keep completed history and immutable provenance. The historical consolidation checkpoint
`f52c857` remains reachable for source comparison; do not rewrite past records to make
unverified work appear complete. Migrate active obligations with evidence and ownership,
not by treating every unchecked historical task as unfinished implementation.

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

- Preserve declared Python compatibility and the existing uv, Ruff, mypy, pytest and import-linter toolchain.
- Use explicit types; do not introduce `from __future__ import annotations`.
- Use `loguru`, pydantic configuration/models, and f-strings.
- Catch specific exceptions. Never silently swallow a failure; use `warning`
  when the caller receives degraded or incomplete results.
- When a loop skips failed items, track and summarize the skipped items.
- Ruff `BLE001` rejects broad exception handlers; do not suppress it.
- Use dynamic attribute access only at opaque third-party SDK boundaries and
  explain why.

## Verification

Read the `verification-workflow` skill when choosing a stage or reporting completion.
Executable definitions and ordering belong to `Taskfile.yml`; invoke them through
`uv run --locked task --exit-code <name>` so child failures retain their exit codes.
Before the outer `uv run`, clear inherited `UV_PROJECT_ENVIRONMENT` so uv uses
this worktree's `.venv`. The Git dispatcher enforces this before invoking uv;
Task fixes child-command cache paths even when cache overrides were inherited.
Task freshness, timestamps and interrupted runs never establish completion.
Do not introduce a separate documentation checker; inspect documentation consistency proportionately.

### Development verification and ownership

Development verification is `verify`: static checks, affected units and packaging,
each invoked once in sequence. It describes the current working copy. Run `fix`
explicitly, inspect its safe fixes and formatting, and stage only task-owned inputs
before committing; fixes never stage files. The hook requires all tracked changes
staged and no nonignored untracked files. It rejects unsuitable inputs before prek
can stash them. Do not edit concurrently with verification in one worktree.

Each worktree owns its environment, testmon history, coverage output and mutable
Ruff/mypy/pytest caches. Do not share verification results across worktrees. Before
heavy work, inspect the machine's reported load and choose `CVETA2_TEST_WORKERS`
within available headroom. Keep `--dist loadgroup`; no shared heavy-job lock is introduced.

Start with focused product tests where useful. The final committed content requires
successful development verification with `SKIP` cleared; reuse an applicable passing
commit-hook run instead of immediately repeating it. After an explicitly deferred
intermediate commit, run `verify` when the final content is ready. Inspect and commit
mechanical fixes separately; rerun checks affected by changed inputs. Documentation consistency is reviewed within the Linear/PR workflow; the always-selected
commit hook still performs development verification.

`test` uses testmon affected selection without a marker expression and excludes
`tests/integration`, including its conftest. `test-full` runs all units while updating
history. Testmon's environment namespace incorporates interpreter identity, locked
dependencies, verification configuration, static test/package assets and complete
relative source/test file membership. An unseen namespace needs a full baseline;
returning to unchanged previously verified inputs may reuse matching history.
Python-content dependency selection remains testmon's responsibility. If an input
class cannot be reliably represented, use `test-full` conservatively. A deselected
test is not a freshly executed test; report the actual selection.

### Acceptance and deferral

Acceptance is the `acceptance` task on a clean committed branch tip: checks,
packaging, randomized property exploration, bounded preflight and full-suite coverage
including live tests. It avoids a duplicate affected-unit run before that full suite.
Code changes also require the mutation skill's explicit report. Survivors are advisory;
tool errors and failing clean tests remain unresolved. These operations are not cached.

Deferred verification means a required live check could not run because infrastructure
is temporarily unavailable: the cluster does not answer, the node cannot admit the
session quota, a timeout, or session services that are not ready within the
cold-start deadline (blocked setup). `infra-check` is read-only and bounded by
`CVETA2_INFRA_CHECK_TIMEOUT` (60 seconds by default): AVAILABLE exits 0, UNAVAILABLE
exits 3, ERROR exits 1. Missing prerequisites, a missing context or a refused
namespace permission are errors, not reasons to wait indefinitely. Preflight
creates nothing. Recheck before every live run. Task-driven availability waiting
remains bounded; explicitly requested operator waiting is separate. Readiness,
seeding and teardown keep their own operation timeouts; the preflight deadline is
not an overall live-suite deadline.

When infrastructure is unavailable, report the reason and deferred checks; continue
independent implementation, documentation, review and local checks. Retry at a meaningful
verification milestone or after evidence of restored availability, without polling.
Repair ordinary code failures within scope. When only blocked verification remains,
stop and ask for the user's decision. Deferral blocks acceptance, merge and release.
Availability disappearing during setup is blocked setup; assertions remain test failures.
Delete the session namespace if it exists and report incomplete cleanup separately.

After parallel integration, verify the combined branch. Substantive behavior, interface,
dependency, security and operational-policy changes require fresh independent review
after integration and verification. Small wording changes may be self-reviewed. Report
passed checks, actual failures, deferred checks and cleanup leftovers distinctly; keep
observed counts and timings in dated evidence. Linear acceptance status keeps deferred verification visibly incomplete.

### Test conventions

Tests observe behavior a caller can see, not third-party tooling or source wording.
Extend existing modules and reuse `tests/fixtures/` and `tests/helpers.py`. Prefer
parametrization or properties for related cases. Assert presentation only where it is
a public CLI contract; never add a test only to kill a default-argument mutant.

Use `properties` to explore randomized inputs before acceptance or after changing a
property. Hypothesis configuration belongs in `tests/conftest.py`; its ignored database
replays failures. Preserve `tests.env_isolation`, which redirects HOME before imports,
and the autouse config/cache/worker cleanup fixtures. Live tests form the `live` xdist
group and must stay serial on one worker. For targeted unit pytest commands exclude
`tests/integration` by directory. pytest-randomly prints its seed; reproduce with
`--randomly-seed=<seed>` or disable with `-p no:randomly` when appropriate.

## Documentation

Keep Russian README and human usage guides accurate when public behavior changes.
They explain usage; current product requirements live in the [Linear contract index](contracts.md).
Update [architecture.md](architecture.md) when module responsibilities change.
Proposed requirement changes remain in Linear issues until implementation is merged
and accepted; then update the current contract with the merged source identity.
Agent instructions, skills, planning and dated evidence are English. Keep observed
counts, timings and deployment status in dated evidence, not evergreen policy.

When transferring requirements, compare original behavior, conditions, limitations
and exceptions, including scenario requirements, with every new authoritative home.
Separate approved policy changes from wording changes. Preserve immutable source
references and require independent semantic comparison. Historical reviews retain
their dispositions and do not automatically become active work queues.

### Project skills

Project skills hold procedures for specific situations; rules that apply to every
task belong in this file. Authored skills live in `.agents/skills/<name>/`, and
`.claude/skills/<name>` is a relative symlink to that directory
(`../../.agents/skills/<name>`), so both hosts read one copy. Add each new
authored skill to the `.agents/skills` exceptions in `.gitignore`.

Archived `speckit-*` skills preserve each host's original contents outside active
discovery. Do not regenerate or invoke frozen tooling during ordinary work.

## Mutation testing

`scripts/mutation.py` mutates the functions a commit changes, in a fresh
workspace exported from the index, and reports survivors without failing (the
`mutation` task), within a budget of 8 functions and 120 s per commit.
Survivors are information: triage behavioural ones and never add a test whose
only purpose is to kill a mutant of a default argument or of wording. Nothing
is cached between runs. Read the
`mutation-testing` skill before triaging survivors or changing the
`[tool.mutmut]` settings.

## Integration tests

The [operational contracts](operational-contracts.md) preserve detailed verification
and session-lifecycle requirements, scenarios and interface contracts. Read them before
changing Task selection, hooks, preflight, infrastructure manifests or lifecycle behavior.

Each live pytest session deploys its own CVAT, MinIO and ClearML into one
Kubernetes namespace of the docker-desktop cluster, `cveta2-it-<id>`, created by
the session with a `ResourceQuota` and `LimitRange` before any workload, reached
only through loopback `kubectl port-forward`, and deleted by exact name on success,
failure and interruption unless `INTEGRATION_KEEP_DATA=1`. The manifests live in
`tests/integration/k8s/`; the quota sizes there are the project's own choice. The
`running-integration-tests` skill owns the session fixture and lifecycle tool,
generated credentials (namespace Secrets and the test process environment only,
never stored or printed), kept sessions, serial execution and teardown.

Never act on a namespace this session did not create: not another session's, not
another project's, not a platform namespace. Use no shared service; the cluster's
dedicated ClearML and MongoDB are not for tests. Request no GPU. Never restart
Docker Desktop or change cluster settings to satisfy a verification gate. The
platform may delete any project namespace 48 hours after creation or after a
restart; a session never depends on an earlier one, and a vanished namespace
needs no repair.

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

Install with `bash scripts/install-hooks.sh`, which preserves the prior installation
for rollback. The shared entry resolves the invoking worktree dynamically. Worktrees
without this Task workflow continue through their existing prek configuration.
The minimal staging shim only validates inputs and invokes prek: it never stages,
deletes or stashes. Mandatory guards live in executable commands, not bypassable
Task preconditions.

The default hook is always-selected, serial `verify`. Conventional Commit validation
remains active. Intentional lockfile-only updates use `build(deps):` and require no
exception. Intermediate task commits may use `SKIP=verify` to defer development
verification explicitly; clear `SKIP` before final verification. There is no pre-push
stage. Manual hook aliases, when present, route to Task; situational skills use Task
directly. A failure caused by unrelated existing work is a reported blocker, not
permission to change or discard that work.

Rebase, cherry-pick and merge do not run pre-commit checks. Verify changed combined
content and use the mutation skill's branch comparison when required. Reuse applicable
successful checks when their inputs remain unchanged. Report the commit, checks,
mutation outcome, remaining worktree state, and any pushed ref confirmed remotely.

### Releases

Code releases are suspended pending separately reviewed PR-based tooling. The configured
semantic-release branch matcher rejects every branch before release processing. Ordinary
build/check/acceptance tasks remain available. Read the `release` skill when a release
is requested; do not restore the matcher or invoke the old merge-and-publish procedure
as part of ordinary delivery.

Replacement tooling must preserve semantic-release ownership of versions, tags and
changelog, immutable accepted-source checks, shared release locking, bounded failure
recovery and separate publication authorization. Publish only Git version tags, never
GitHub Releases, release assets or packages. Failed or deferred required acceptance
blocks release. The existing `release-check` command remains checks only; it does not
authorize a release or restore the old verification exception. Any restored exception
must remain limited to version/changelog/lockfile changes with explicit release checks,
Conventional Commit validation and staging guards intact.

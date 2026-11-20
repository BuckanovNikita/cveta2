# cveta2 agent instructions

cveta2 is a Python CLI and Python API for CVAT annotation projects. It fetches
bounding-box annotations, partitions them by task completion state, downloads images
from S3, converts to and from YOLO and COCO, uploads tasks, manages project labels and
verifies, prepares and publishes datasets to ClearML. [README.md](README.md) (Russian)
is the user guide. [DOCS.md](DOCS.md) is the reference: architecture, terms, decisions,
CLI, configuration, formats, live infrastructure and release operations. Read the
matching DOCS.md section before changing that area.

## Environment

- Clear an inherited `UV_PROJECT_ENVIRONMENT` (`unset UV_PROJECT_ENVIRONMENT`), then
  `uv sync --locked`. Run every Python tool through `uv run --locked`.
- Each worktree owns its `.venv`, `.testmondata`, `.coverage`, `.ruff_cache`,
  `.mypy_cache`; Task pins them to the worktree root. Never share results across worktrees.
- Live tests also need `kubectl` with the `docker-desktop` context. Nothing else: no Helm,
  shared stand, other repository or local CA.
- Live tests run on the shared local Kubernetes test infrastructure; its operating guide is
  the AGENTS.md and DOCS.md of the k8s-infra repository. Read it only for platform
  behavior (sweeper, protected namespaces); never use its stands, helpers or services.

## Checks

There are no git hooks. Run checks directly. Task stages:
`uv run --locked task --exit-code <stage>` (`--exit-code` keeps child exit codes).
`Taskfile.yml` owns every stage, its commands and their order.

- `CVETA2_TEST_WORKERS` sets xdist workers; choose it from the machine's
  reported load. There is no shared heavy-job lock.
- Before every commit run `fix`, inspect its edits, stage exact task-owned paths
  (`git add -- <path>`), then run `verify` on the final content. Nothing enforces this or
  the commit message format; it is policy. Do not edit files while `verify` runs.
  `verify` checks the working tree, not the index: before relying on it for a commit,
  leave no unstaged tracked changes or untracked non-ignored files.
- Intermediate task commits may defer `verify`; the final content must pass it.
- Task keeps no freshness cache. Task state, timestamps, `.cache/` logs and interrupted
  runs never establish success. A testmon-deselected test is not an executed test; use
  `test-full` when testmon cannot represent a changed input (non-Python assets, plugins).
- Selection: any change needs `verify`. Documentation-only changes need only `verify`
  (`pyproject.toml`, `Taskfile.yml`, presets and scripts are not documentation). Other
  changes also need the mutation report (`mutation -- --base main`) and `acceptance` on a
  clean committed tip, with no duplicate affected-unit run before it. Changes to build
  settings or sdist contents need `build`; property-test changes need `properties`.
- Reuse a passing check only while its inputs are unchanged. Mutation, properties,
  preflight, live tests and releases are never cached.

### Mutation report

- Scope, limits and flags: the `scripts/mutation.py` docstring and `--help`.
- Exit 0 report (survivors advisory), 1 survivors under `--strict`, 2 tool, config,
  clean-test failure or "no verdict" (rerun with a larger budget).
- Survivors are advisory. Triage only behavioural ones. Never add a test only to kill a
  default-argument or wording mutant; never reshape correct code to stop a mutant.
  Report functions mutated, killed/survived/not-reached/not-run counts and each
  survivor's classification.
- `[tool.mutmut]` invariants: `pytest_add_cli_args` keeps `-n 0` and its `--ignore` list;
  `mutate_only_covered_lines` stays off (breaks the numpy import); never check in
  `only_mutate`; `do_not_mutate_patterns` holds presentation surfaces only.

### Live tests

- Exit codes of `infra-check`: 0 AVAILABLE, 3 UNAVAILABLE (cluster silent, node cannot
  admit the quota, timeout), 1 ERROR (missing kubectl/context, namespace permission
  refused, unexpected failure). Diagnose ERROR; never wait on it.
- UNAVAILABLE or blocked setup means deferred, not failed. Deferred live checks block
  acceptance, merge readiness and release until they pass or the user waives them.
  Continue independent work, retry at a milestone without polling, and ask the user when
  only blocked verification remains. A passing preflight without executed live tests is
  not acceptance.
- Waivers: only the user waives, by stating it or by a human merge of a PR whose
  description lists the gate as not run ("waived by merge"). A waiver is never a pass.
- Run live tests only through `integration` or `acceptance`. For a focused selector run
  `infra-check` first and keep `CVETA2_TASK_VERIFICATION=1` and `--dist loadgroup`.
  Live tests are the `live` xdist group; never split it across workers (each worker would
  start its own session). Targeted unit runs exclude `tests/integration` by directory.
- Never act on a namespace this session did not create (another session's, another
  project's, or a platform namespace). Never use the cluster's dedicated ClearML or
  MongoDB. Never request `nvidia.com/gpu`. Never restart Docker Desktop or change cluster
  settings to pass a gate. Never rely on data from an earlier session: the platform may
  delete any project namespace after 48 hours or a restart.
- Session credentials live only in namespace Secrets and the test process environment.
  Never print, log or write them to tracked files.
- After a failed or interrupted run, prove cleanup: `kubectl --context docker-desktop get ns`
  and no remaining `kubectl --context docker-desktop -n <ns> port-forward` process. Report
  leftovers by name with `uv run --locked python -m tests.integration.lifecycle stop <ns>`.
- Manifests: plain kubectl, pinned image tags, `emptyDir` or a claim with
  `storageClassName: hostpath` only where pods share files; never `local-path` or
  `/mnt/wsl/data/k8s-volumes`; loopback port-forward only (no Ingress, NodePort, host
  port, local CA). The CVAT server version (`cvat/server:v2.59.1`) stays pinned;
  upgrading any service is a separate change.

## Architecture boundaries

- Layers, SDK owners and adapter independence are the import-linter contracts in
  `pyproject.toml`. `clearml` is imported lazily, so CSV verification works without the
  `clearml` extra.
- Domain and application use only lexical paths, in-memory pandas, Pydantic and Loguru.
  File/pandas IO, config and env discovery, SDK/network IO, clocks, prompts and threads
  belong to adapters, composition or interfaces. Inject runners, clocks and locks
  explicitly; no global service locator.
- Application use cases and the public API never prompt and raise `Cveta2Error`. Only
  `interfaces/commands/` own prompts, argument mapping and `sys.exit`; credentials are
  prompted only in `interfaces/commands/_bootstrap.py:open_client()`.
- Public facades keep imports, signatures and model/exception identities. Removed internal
  packages (`services/`, `commands/`, `_client/`, `_client_ops/`, `_clearml/`) are not
  compatibility promises.
- After changing boundaries run `lint-imports` and `tests/test_architecture.py` (it runs
  the AST effect checker `tests/architecture_effects.py`). Where an affected boundary lacks
  enforcement, add a scoped contract and a forbidden-dependency negative fixture.

## Code and test standards

- Python: explicit types, never `from __future__ import annotations`, syntax within 3.12;
  Loguru, Pydantic, f-strings, pytest. Preserve public imports, CLI output, exit codes,
  config precedence, serialized formats and persisted-data compatibility.
- Catch specific exceptions where handled, keep the cause; Ruff `BLE001` stays unsuppressed.
  Never swallow failures: `warning` for degraded results, summarize skipped loop items.
- Avoid `getattr`: dynamic attribute access only at opaque third-party SDK boundaries,
  with a comment saying why.
- mypy overrides stay scoped to affected modules; stubs over `ignore_missing_imports`
  or `Any`.
- uv: `uv add`/`uv remove` in the right group or extra, inspect the lock diff, never
  `uv lock --upgrade` to repair a lock. Remove code only with evidence of no consumers.
- Tests observe caller-visible behavior; extend existing modules, reuse `tests/fixtures/`
  and `tests/helpers.py`, prefer parametrization or Hypothesis properties; assert wording
  only where it is a public CLI contract.
- Preserve `tests.env_isolation` (redirects HOME and XDG before imports) and the autouse
  config/cache/worker fixtures in `tests/conftest.py`; tests never touch a real
  `~/.config/cveta2/config.yaml`. `CVETA2_LIVE_EXPORTED` hides live-session variables from
  unit tests.

## Product rules that bind code changes

- Linear contract documents are the product authority. Check the matching one before
  changing commands, config fields, API return values or serialized formats (links in
  [DOCS.md](DOCS.md#decisions)). README, CLI output and user-facing messages are Russian.
- Recency per image is the highest `task_id`, never `task_updated_date` (a project label
  edit rewrites it on every task). `domain/partition.py` concatenates deletion records
  before annotation records so a deletion wins a same-task tie.
- A task is complete only when every job, including Ground Truth, is acceptance/completed.
- Never retry a non-idempotent CVAT write on 5xx, including 503 with Retry-After: CVAT
  appends annotations, so a replay duplicates boxes. Such writes retry only on 429.
- Interactive prompts live only in the CLI. `CVETA2_NO_INTERACTIVE=true` turns every
  missing decision into an error naming the flag.
- The personal config never overrides the shared project config; exactly one shared file
  loads, and a bad selection fails without fallback.
- Automatic ClearML publication (`setup-clearml`, `fetch --no-clearml`, `publish_clearml`,
  `CVETA2_CLEARML`) was removed; do not reintroduce it. Publication runs only through
  `verify --bundle` + `upload-dataset` or `dataset prepare` + `dataset publish`.
- Distinct images need unique basenames and unique stems per project or dataset.
- Bump `CACHE_SCHEMA_VERSION` (`domain/cache.py`) or `MANIFEST_SCHEMA_VERSION`
  (`domain/upload.py`) when their stored formats change.
- Retired shared-stand names must not return: `INFRA_RUN_TAG`, `INFRA_PROJECT`,
  `INFRA_REGISTRY`, `K8S_INFRA_SKILL_DIR`, `INTEGRATION_SKILL_DIR`, `.run-tag`, `cveta2-main`,
  and invoking k8s-infra helpers `infra/clearml/mongodb/cvat/lakefs/postgres/minio.py`
  (same-named product modules are fine). Operators drop these exports from shell profiles.

## Delivery and release

- Every change goes through a Linear issue in team `SIP`, project `cveta2`, a task branch
  and a GitHub PR on `BuckanovNikita/cveta2`. Agents commit, push task branches over the
  existing SSH remote and open PRs. Humans merge into `main`. Explicit session restrictions
  and host read-only modes override this.
- Never push `main`, merge locally into `main`, create/push/move/delete tags, run
  `semantic-release` in a writing mode (`--noop` is fine), publish a GitHub Release or
  package, or force-push anything but task-owned branches (`--force-with-lease`).
- Linear states: Backlog, Todo, In Progress, In Review, Done, Canceled, Duplicate.
  Readiness labels are separate: `needs-triage`, `needs-info`, `ready-for-agent`,
  `ready-for-human`, `wontfix` (with Canceled); a label never overrides a blocker. Mark an
  implementation issue Done only after it reaches `main` and acceptance passed or every
  missing gate is recorded waived. Record checks, deferrals and waivers in the issue.
- If Linear is unavailable, implement in isolation against a recorded, previously
  verified contract snapshot and defer requirement decisions and merge readiness.
- After a human merge and acceptance, update the affected Linear contract with the merged
  SHA; no automation does it.
- Commit messages: `type(scope)!: description`, lowercase type from build, chore, ci,
  docs, feat, fix, perf, refactor, style, test. Reword git's `Revert "..."` subject.
- A human merge into `main` is the only release trigger. `feat`, `fix`, `perf` and `!`
  bump the version; `!` needs a `BREAKING CHANGE:` footer; while 0.x a breaking change
  bumps the minor. The parser also reads every squash-body paragraph that looks like a
  Conventional Commit header, and a `BREAKING CHANGE:` footer anywhere in the squash body
  also bumps, so check the PR title, squashed headers and footers before merge.
- A release commit on `main` without its `v<version>` tag is stop-and-report: nothing more
  is merged until a human pushes that tag. Recovery details: [DOCS.md](DOCS.md#release-operations).

## Known pitfalls

- A focused live run without `CVETA2_TASK_VERIFICATION=1` waits on an unavailable cluster.
- A kept session (`lifecycle up` or `INTEGRATION_KEEP_DATA=1`) blocks `up` and keep-mode
  pytest in that checkout until `lifecycle stop`.
- `env` refuses a terminal: use `eval "$(uv run --locked python -m tests.integration.lifecycle env)"`.
- Without the `AWS_*` session variables, live S3 tests fail with `NoCredentialsError`.
- The `release` workflow exits green with "already been released" when the tag exists;
  read the run log, not the status.

## Working agreement
- At the start of work, state the worktree path, the current branch and its relation to the default branch; say when remote refs were not fetched.
- Inspect existing and staged changes before editing. Preserve unrelated work and local overrides; stage only task-owned paths and inspect the staged diff.
- Report what each executed check establishes and what remains unverified; distinguish mocked checks, live outcomes and historical evidence. Clean up task-owned processes and temporary resources.
- Tests must exercise product code, never project tooling.
- Changes to behavior, interfaces, dependencies, security or operational policy need a fresh independent review after integration and verification. Small wording edits may be self-reviewed.
- Split large work into independent delegated tasks with explicit write ownership and acceptance evidence; delegated agents do not delegate further.
- Use Conventional Commits. Commit automatic formatting separately from logic. Local commits within the task scope need no approval.
- README.md is Russian; AGENTS.md and DOCS.md are English. Keep observed counts, timings and deployment status out of both files.
- Keep machine-specific paths, endpoints and settings in local configuration, not in these files.

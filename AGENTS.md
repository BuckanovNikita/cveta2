# cveta2 repository guidance

## Project

cveta2 is a Python 3.10+ CLI and API for CVAT annotation projects. It fetches
bounding-box annotations, partitions them by task completion state, downloads
images from S3, uploads datasets, and manages project labels. Run Python tools
through `uv run`.

User documentation and user-facing messages are Russian. Repository guidance,
`ARCHITECTURE.md`, and `DATASET_FORMAT.md` are English. This file is
`AGENTS.md`; `CLAUDE.md` is a symlink to it, so edit only `AGENTS.md`.

## Preserve the working tree

Before editing, inspect `git status --short`, the relevant diff, and the staged
diff. Treat existing modifications and untracked files as user work. Do not
stash, reset, broadly stage, commit, or push them. Stage and commit only exact
task-owned paths when the user asks for a commit; use the project `commit`
skill for that workflow.

## Architecture

The import-linter contract in `pyproject.toml` enforces:

```text
cli → commands → api → services → _clearml → client → _client_ops → _client
      ↓
   models, exceptions, config
```

Higher layers may import lower ones. `commands/` contains thin CLI adapters
(prompts, argument mapping, and `sys.exit`); orchestration belongs in
`services/`, which must not prompt or exit and raises `Cveta2Error`.
`api.py` exposes prompt-free public functions. Keep every `cvat_sdk` import
inside `_client/`.

Read `ARCHITECTURE.md` before changing layer flow, `ORG/PROJECT` resolution,
or fetch/upload/convert behavior. CVAT retains shapes for deleted frames, so
`dataset_partition.py` concatenates deletion records before annotation records
to win same-task ties. Recency uses `task_id`, never
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
behavior.

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

This project is `cveta2` in the k8s-infra registry and may use the shared
stands `cvat`, `minio`, `clearml` on the docker-desktop cluster as identity `cveta2`. The
skill is `/mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra` (its `projects.toml` is the registry); read its
`references/run-contract.md` before touching a stand.

- Preflight: `python3 /mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra/scripts/infra.py room`; obey WAIT (exit status 3).
- Mint one tag per run and export it (assign, then export, so a refused mint
  stops you instead of exporting an empty tag):
  `INFRA_RUN_TAG=$(python3 /mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra/scripts/infra.py newtag --project cveta2 --slug <what>) && export INFRA_RUN_TAG`
  Not Claude Code? Export `INFRA_HARNESS=codex|ci|human` first; the default is `claude`.
- Name everything you create by `$INFRA_RUN_TAG` as the stand reference says.
- Credentials come from the helpers, never from files:
  `eval "$(python3 /mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra/scripts/cvat.py --project cveta2 env)"`
  `eval "$(python3 /mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra/scripts/minio.py --project cveta2 env)"`
  `eval "$(python3 /mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra/scripts/clearml.py --project cveta2 env)"`
- Clean up on success and on failure, then prove it with `ls`:
  `python3 /mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra/scripts/cvat.py --project cveta2 cleanup --prefix "$INFRA_RUN_TAG"`
  `python3 /mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra/scripts/minio.py --project cveta2 cleanup --prefix "$INFRA_RUN_TAG"`
  `python3 /mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra/scripts/clearml.py --project cveta2 cleanup --prefix "$INFRA_RUN_TAG"`
- Caps are `[capacity]` keys in `/mnt/wsl/data/nkt/k8s-infra/skills/k8s-infra/projects.toml`: `sandbox_runs_soft`
  bounds every run, `cveta2_integration_runs` the cveta2 suites, `gpu_runs` the
  trainings, `lakefs_heavy_runs` the lakeFS-heavy runs; `room` enforces
  `max_pods_soft`, `fat_stand_max` and `clearml_max_task_pods`.
- Never run `cleanup --stale` without `--dry-run`. Never touch another tag or a
  durable name. Report anything intentionally kept by its full name.

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
and commit semantics live in `CONTRIBUTING.md`. Do not release, push, commit,
or change remotes unless requested.

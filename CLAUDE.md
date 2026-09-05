# cveta2 repository guidance

## Project

cveta2 is a Python 3.10+ CLI and API for CVAT annotation projects. It fetches
bounding-box annotations, partitions them by task completion state, downloads
images from S3, uploads datasets, and manages project labels. Run Python tools
through `uv run`.

User documentation and user-facing messages are Russian. Repository guidance,
`ARCHITECTURE.md`, and `DATASET_FORMAT.md` are English.

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

Live tests use the persistent CVAT stand at `http://cvat.k8s.localhost` plus a
per-run MinIO/ClearML Compose stack. The `running-integration-tests` skill owns
credential bootstrap, unique run tags, serial pytest execution, and exact-tag
cleanup. Do not start, stop, or clean the stand manually.

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
gate when `tests/integration/.env` exists. The live gate can replace objects
owned by its run tag; the integration skill defines that boundary.

`main` changes only by merge. On `main`, semantic-release derives versions,
tags, and `CHANGELOG.md`; never hand-edit the project version. Release commands
and commit semantics live in `CONTRIBUTING.md`. Do not release, push, commit,
or change remotes unless requested.

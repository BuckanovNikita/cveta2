# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**cveta2** is a Python CLI and API for working with CVAT annotation projects. It fetches bbox annotations from CVAT, partitions them into dataset/obsolete/in_progress based on task completion status, downloads images from S3, uploads annotated datasets back to CVAT, and manages project labels.

**Language**: Python 3.10+, Russian documentation (README.md, user-facing messages)

## Development Commands

All tools run via `uv run`:

```bash
# Run tests
uv run pytest              # full suite with parallel execution
uv run pytest -x           # stop on first failure
uv run pytest -k "test_name"  # run specific tests

# The commit gate, without making a commit (git commit runs it too)
uv run pre-commit run --all-files

# Individual tools
uv run ruff format .       # format code
uv run ruff check .        # lint
uv run ruff check --fix .  # auto-fix
uv run mypy .              # type check
uv run lint-imports        # architecture contracts
uv run vulture             # dead code detection
./scripts/mutation_test.sh --profile fast  # mutation testing gate (pre-commit subset)
./scripts/mutation_test.sh --profile full  # mutation testing gate (whole scope, pre-push)
./scripts/integration_gate.sh              # integration gate: stack up, tests, keep on main / stop elsewhere (pre-push)
```

**Style**: Always use `loguru` for logging (never `print`), pydantic for configs, f-strings over structured logging.

**Error handling conventions**:
- Never use bare `except Exception` — catch specific exception types relevant to the operation (e.g. `pd.errors.ParserError`, `KeyError`, `OSError`).
- Never silently swallow exceptions. At minimum, log at `info` level so failures are traceable. Use `warning` when the caller gets incomplete/degraded results.
- When skipping items in a loop due to errors, track which items were skipped and log a summary after the loop so the user knows results may be incomplete.
- Ruff enforces this: the `BLE001` rule bans broad `except` clauses. Do not suppress it with `# noqa`.

## Architecture

**Layered architecture** enforced by import-linter (see `pyproject.toml`):

```
cli → commands → api → services → _clearml → client → _client_ops → _client
      ↓
   models, exceptions, config (foundation - no upward imports)
```

Higher layers may import lower ones, never the reverse. `commands` are thin
CLI adapters (prompts + arg mapping + `sys.exit` only); the real orchestration
lives in `services` (pure, no prompts/`sys.exit`, raise `Cveta2Error`). `api`
exposes those services as prompt-free module-level functions. All `cvat_sdk`
code is confined to `_client`.

Package map, one line each:

- `cli.py` argparse entry point → `commands/` adapters → `api.py` (CLI-mirroring public functions) → `services/` orchestration
- `client.py` composes the `_client_ops/` mixins (SDK-free domain calls); `_client/` holds every `cvat_sdk` import behind the `CvatApiPort` protocols
- `dataset_partition.py` splits annotations into dataset/obsolete/in_progress; `task_cache.py` caches completed-task annotations locally + on S3
- `models.py`, `config.py`, `exceptions.py` are the foundation; `image_downloader.py` / `image_uploader.py` / `projects_cache.py` are leaf utilities; `_clearml/` is an isolated optional layer

**Read [ARCHITECTURE.md](ARCHITECTURE.md)** before changing how a command flows
through the layers: it holds the per-module map, the fetch/upload/convert data
flows, `ORG/PROJECT` spec resolution, and the deleted-images and task-by-task
details.

The one gotcha worth carrying everywhere: CVAT keeps annotation shapes for
frames marked deleted, so `dataset_partition.py` concatenates deletion records
**before** annotation records to win same-**task** ties. Recency is ordered by
`task_id`, never by `task_updated_date` — editing a project's labels bumps that
date on every task at once.

## Testing

```bash
uv run pytest                    # all tests (parallel)
uv run pytest tests/test_partition.py  # specific module
uv run pytest -k "deleted"       # by name pattern
uv run pytest -x                 # stop on first failure
```

**Test structure**:
- Unit tests mock `CvatApiPort` using `FakeCvatApi` (`tests/fixtures/fake_cvat_api.py`, an in-memory CVAT)
- Fixtures in `tests/fixtures/cvat/` contain real CVAT JSON snapshots (`coco8-dev/` is the seeded project)
- **`tests/helpers.py`** holds shared builders (annotations, DataFrames, fakes); `conftest.py` holds fixtures only
- An autouse fixture in `conftest.py` sets `CVETA2_DISABLE_CACHE=true` for every test — cache tests opt back in explicitly
- **`tests/test_fetch_service.py`** is the canonical owner of the coco8 fetch scenarios
- **`tests/test_api.py`** covers the public `cveta2.*` workflow functions; **`tests/test_cli_parsing.py`** covers argparse wiring

Integration tests (`tests/integration/`) run only when `CVAT_INTEGRATION_HOST`
is set, against the cluster CVAT stand plus a MinIO + ClearML compose stack,
and at pre-push through `scripts/integration_gate.sh` on machines that have
`tests/integration/.env`. The lifecycle scripts, the `.env` keys, the run tag
that isolates parallel agents and the keep-on-main rule live in the
**`running-integration-tests` skill** — use it rather than starting the stack
by hand.

## Mutation Testing

`./scripts/mutation_test.sh` gates the modules in `[tool.mutmut].only_mutate`
and fails on any unexplained survivor. Scope is a **ratchet**: a module joins
`only_mutate` in the same commit that takes it to zero survivors.

**Read the `mutation-testing` skill** before triaging a survivor, editing
`only_mutate` or `[tool.cveta2.mutation.equivalent]`, or judging whether a
module is worth gating. It carries the rules that fail silently otherwise —
never reshape working code to satisfy the gate, allowlist entries go stale on
renumbering — plus a reference file on what mutmut actually mutates.

## Branching and releases

Work happens on a branch; `main` only ever changes by merging one in. **Every
change to `main` ends with a release** — python-semantic-release derives the
version, the annotated `vX.Y.Z` tag and `CHANGELOG.md` from the conventional
commits that were merged. Never hand-edit `version` in `pyproject.toml`.

From `main`, right after the merge:

```bash
uv run semantic-release version --print                     # what the next version would be
uv run semantic-release version --no-push --no-vcs-release
git push origin main --follow-tags
```

- A merge of only `chore`/`docs`/`test` commits warrants no release; `--print`
  says so and exits 0. Still run it — that is how you learn which case you are in.
- The push is separate on purpose: it fires the pre-push gates (full mutation
  scope, version drift, integration tests).
- Releases never run from a feature branch — semantic-release refuses, since only
  `main` is a release branch.
- No CI, no GitHub Release, no PyPI. A release is a tag, a changelog and a version.

The bump rules, the `BREAKING CHANGE:` footer convention and what is excluded
from the changelog are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Configuration

Config loaded via `CvatConfig.load()` from:
1. Environment variables (`CVAT_HOST`, `CVAT_USERNAME`, `CVAT_PASSWORD`, `CVAT_ORGANIZATION`, `CVETA2_DATA_TIMEOUT`)
2. `~/.config/cveta2/config.yaml` (or `CVETA2_CONFIG`)
3. Built-in preset (`cveta2/presets/default.yaml`)

Env vars that change behaviour under test or in CI:

- `CVETA2_DISABLE_CACHE=true` — fully disables the task-annotation cache (no reads, writes, S3 backfill or prune); equivalent to always passing `--no-cache`
- `CVETA2_NO_INTERACTIVE=true` — disables all prompts
- `CVETA2_RAISE_ON_FAILURE=true` — abort on the first CVAT 5xx during fetch instead of skipping that task with a warning
- `CVETA2_DATA_TIMEOUT` — opt-in read timeout in seconds for CVAT and S3 requests, overriding the `cvat.request_timeout` config field (connect timeout fixed at 10s); unset or `0` = no timeout
- `CVETA2_CLEARML=false` — disable ClearML dataset publishing for this run,
  equivalent to `fetch --no-clearml`
- `CVETA2_S3_WORKERS` / `CVETA2_CVAT_WORKERS` / `CVETA2_RETRY_ATTEMPTS` — one-run overrides for the `network` config section (parallel S3 transfers, parallel CVAT requests, total attempts per request)

The `sync_roots`, `cache` and `image_cache` config sections (image-cache roots,
`ignored_prefix`, `task_cache_s3`, per-project download sources) are documented
for users in [docs/configuration.md](docs/configuration.md); `cveta2 setup-cache`
writes them interactively.

## Important Files

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Module map, data flows, layer details
- **CONTRIBUTING.md** - Style guide, linter setup, documentation rules (Russian)
- **DATASET_FORMAT.md** - Output CSV format, data model reference
- **README.md** - User entry point (Russian); the reference lives in `docs/`
- **docs/** - User reference, Russian: `cli.md` (every command and flag),
  `configuration.md` (config file, env vars, parallelism, retries,
  non-interactive mode), `images-and-cache.md` (S3 images, task cache, ClearML),
  `python-api.md`
- **pyproject.toml** - Dependencies, tool configs, import-linter contracts

**Documentation language.** Russian: `README.md`, `CONTRIBUTING.md`, `docs/`.
English: `CLAUDE.md`, `ARCHITECTURE.md`, `DATASET_FORMAT.md`.
`tests/test_docs.py` enforces this, along with three other checks that keep the
docs from drifting: every documented Python example must match a real signature,
every command / flag / env var / config field must be documented, and every
relative link and anchor must resolve. Update `docs/` in the same commit that
changes the CLI or the API.

## Common Tasks

**Add new command**:
1. Add the orchestration to `cveta2/services/` (pure, no prompts/`sys.exit`; raise `Cveta2Error`)
2. Create `cveta2/commands/mycommand.py` with `run_mycommand(args: argparse.Namespace)` — a thin adapter that resolves prompts, opens a client via `open_client()`, and calls the service
3. Expose it as a `cveta2.mycommand(...)` function in `cveta2/api.py` (no prompts; raise on missing settings)
4. Add subparser in `cveta2/cli.py`
5. Document it in `docs/cli.md`, and add a row to the command index in README.md (Russian)

**Modify partition logic**:
1. Edit `cveta2/dataset_partition.py`
2. Add test case in `tests/test_partition.py`
3. Run `uv run pytest tests/test_partition.py tests/test_fetch_service.py`

**Update data models**:
1. Edit pydantic models in `cveta2/models.py`
2. Update `DATASET_FORMAT.md` if CSV columns change
3. Ensure tests in `tests/test_extractors.py` pass

## Hooks

One command installs every stage — `default_install_hook_types` in
`.pre-commit-config.yaml` covers `pre-commit`, `commit-msg` and `pre-push`:

```bash
uv run pre-commit install
```

**commit** — format → lint → import-linter → mypy → vulture → pytest → mutmut
(fast profile) → count-lines → build → lock. `git commit` runs it, and unstaged
changes are stashed for the run, so what is checked is what is being committed.
A hook that rewrites files (ruff format, `uv lock`) aborts the commit —
re-`git add` and commit again.

**commit-msg** — `conventional-commit` rejects a subject python-semantic-release
cannot parse, and a `!` marker with no `BREAKING CHANGE:` footer. Merge, revert
and autosquash subjects are exempt.

**pre-push** — `mutmut-full` over the whole gated mutation scope, then
`version-drift` (the `version` field must match the nearest tag, so a hand edit
cannot reach `main`), then `integration-tests`.

`integration-tests` runs `scripts/integration_gate.sh`: it recreates this
run's MinIO + ClearML compose stack and its project on the cluster CVAT stand
(`http://cvat.k8s.localhost`), runs `tests/integration`, then either keeps the
run for inspection (a push of `main`) or removes it (any other branch). It arms
itself on `tests/integration/.env`: no such file, no integration tests, which
is what a fresh clone and every other machine gets. **A push therefore
replaces the compose stack and the CVAT project of your run tag** —
`integration_up.sh` starts with `down -v` and `cvat_stand.py cleanup --tag`.
Skip it for one push with `SKIP=integration-tests git push`.

To run one hook by hand: `uv run pre-commit run --all-files`, or
`uv run pre-commit run <id> --hook-stage pre-push`.

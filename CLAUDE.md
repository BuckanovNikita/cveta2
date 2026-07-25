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

# Pre-commit checks (runs all tools in order)
uv run pre-commit run --all-files

# Individual tools
uv run ruff format .       # format code
uv run ruff check .        # lint
uv run ruff check --fix .  # auto-fix
uv run mypy .              # type check
uv run lint-imports        # architecture contracts
uv run vulture             # dead code detection
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
cli → commands → api → services → _clearml → client → _client
      ↓
   models, exceptions, config (foundation - no upward imports)
```

Higher layers may import lower ones, never the reverse. `commands` are thin
CLI adapters (prompts + arg mapping + `sys.exit` only); the real orchestration
lives in `services` (pure, no prompts/`sys.exit`, raise `Cveta2Error`). `api`
exposes those services as prompt-free module-level functions. All `cvat_sdk`
code is confined to `_client`.

### Module Organization

- **`cveta2/cli.py`** - Argparse CLI entry point, dispatches to commands
- **`cveta2/commands/`** - Thin CLI adapters (prompts, arg mapping, `sys.exit`; delegate to `services`):
  - `fetch.py` - Fetch annotations from CVAT project
  - `upload.py` - Upload annotated dataset back to CVAT
  - `convert.py` - Bidirectional CSV ↔ YOLO conversion, plus CSV → COCO export
  - `merge.py` - Merge multiple fetch outputs
  - `labels.py` - Manage project labels
  - `s3_sync.py` - Download images from S3
  - `setup.py` / `setup_clearml.py` - Initial config and project cache setup
  - `ignore.py` - Mark tasks to skip during fetch
  - `task_ops.py` - `task` subcommands: mark-deleted, drop-label, delete, status
  - `whats_new.py` - List tasks completed after a fetched dataset CSV
  - `doctor.py` - Diagnostic checks
  - `_bootstrap.py` - `open_client()`: single config load, host check, timeout setup, credential prompt (the ONLY place prompting happens)
  - `_task_selector.py` / `_helpers.py` - Shared internals
- **`cveta2/api.py`** - Public workflow functions mirroring the CLI 1:1 (`fetch`, `upload`, `convert_*`, `merge`, `whats_new`, `s3_sync`, `get_labels`, `update_labels`, `task_*`), re-exported from `cveta2/__init__.py`. Never prompts — missing settings raise `MissingHostError` / `MissingCredentialsError`.
- **`cveta2/services/`** - Orchestration (no prompts, no `sys.exit`; raise `Cveta2Error`):
  - `fetch.py` - `fetch_project()` / `fetch_selected_tasks()` pipelines
  - `upload.py` - `upload_dataset()` + plan building / filtering helpers
  - `convert/{common,yolo,coco}.py` - CSV ↔ YOLO / COCO conversion
  - `merge.py` - `merge_datasets()`
  - `output.py` - CSV read/write, path enrichment
  - `resolve.py` - project resolution (`ORG/PROJECT` spec parsing, org switching, project-from-task inference) and `sync_roots` override
  - `whats_new.py` - cutoff computation
- **`cveta2/client.py`** - High-level `CvatClient` domain orchestration over the port (SDK-free; requires a context manager for remote calls, never prompts)
- **`cveta2/_client/`** - All CVAT SDK code (internal):
  - `ports.py` - `CvatReadPort` + `CvatWritePort` protocols (combined as `CvatApiPort`; enables test fakes)
  - `sdk_adapter.py` - Implements both ports over `cvat_sdk`; translates SDK errors to `CvatApiError`
  - `sdk_requests.py` - Builds SDK request models
  - `connection.py` - Opens SDK clients, configures data timeout
  - `assembly.py` - Pure DTO → domain transforms
  - `extractors.py` - Converts CVAT shapes to `BBoxAnnotation`
  - `dtos.py` - Raw CVAT data transfer objects
  - `context.py` - API context management
  - `mapping.py` - Data mapping utilities
- **`cveta2/_clearml/`** - Optional ClearML dataset publishing (isolated layer)
- **`cveta2/models.py`** - Pydantic data models (BBoxAnnotation with optional `confidence`, DeletedImage, etc.)
- **`cveta2/config.py`** - Config loading (YAML + env vars + presets)
- **`cveta2/dataset_partition.py`** - Core logic: splits annotations into dataset/obsolete/in_progress
- **`cveta2/task_cache.py`** - Cache of completed-task annotations: local dir + shared S3 mirror, invalidated by task `updated_date`
- **`cveta2/image_downloader.py`** - S3 → local sync
- **`cveta2/image_uploader.py`** - Local → S3 upload (organizes into `YYYY-MM/` subfolders)
- **`cveta2/s3_types.py`** - `S3Client` Protocol (interface for S3 operations)
- **`cveta2/projects_cache.py`** - Local project metadata cache, keyed by organization (`organizations: [{slug, name, projects}]`; `""` slug = personal workspace)

### Key Data Flow

1. **Fetch**: `cli`/`api.fetch` → `commands/fetch.py` (or `api.py`) → `services/fetch.py:fetch_project()` → `client.fetch_one_task()` per task → `_client/sdk_adapter.py` → CVAT API
   - Completed tasks are served from `task_cache.py` when the cached `task_updated_date` matches (local `~/.cache/cveta2/task_annotations/`, backfilled from the project bucket's `<prefix>/.cveta2_cache/`); `--no-cache` / `--force` / `CVETA2_DISABLE_CACHE=true` override, full fetch prunes orphaned local entries
   - Returns `ProjectAnnotations(annotations, deleted_images)`
   - Annotations converted to `BBoxAnnotation` by `extractors.py`
   - Result partitioned by `dataset_partition.py` into dataset/obsolete/in_progress CSV files

2. **Upload**: `commands/upload.py` (or `api.upload`) → `services/upload.py:upload_dataset()` → `client.create_upload_task()` + `client.upload_task_annotations()`
   - Reads CSV, uploads images to S3 (into `YYYY-MM/` subfolders), creates CVAT task, uploads annotations
   - Label selection is frame-based: a selected label pulls in all annotations of its frames (co-occurring labels included and validated against project labels); `--labels all` selects every dataset label plus unannotated frames (a literal dataset label named `all` wins over the shortcut)
   - Rows with `issue_state="new"` and non-empty `issue_text` become open CVAT issues **attached to the row's bbox**; rows with issue text but no complete bbox are skipped with a warning (no full-frame issues)

3. **Convert**: `commands/convert.py` (or `api.convert_*`) → `services/convert/`: `convert_to_yolo` exports CSV to YOLO format (images + labels), `convert_from_yolo` imports YOLO predictions back to CSV, `convert_to_coco` exports COCO detection format. Uses `PixelBox`/`YoloBox` NamedTuples for coordinate conversion.

4. **Partition Logic** (`dataset_partition.py`):
   - For each image, finds **latest task** by `task_updated_date` (comparing annotations + deletions)
   - If latest task is deletion → image goes to `obsolete`, added to `deleted_images`
   - Otherwise: completed tasks → `dataset` (latest) or `obsolete` (stale), non-completed → `in_progress`
   - **Important**: Deletion records are concatenated **before** annotation records to win ties (same date)

### Project Specs and Organizations

- Every project spec (CLI `-p`, API `project=`) accepts an id, a name, or `ORG/PROJECT` (`/PROJECT` = personal workspace). The org prefix calls `client.set_organization()`, switching the session org for all subsequent CVAT calls (`services/resolve.py:split_project_spec` / `apply_project_org`).
- The interactive picker (`commands/interactive/entities.py:select_project`) pages projects by organization — first page is the config org — and switches the session org on selection. Echoed re-run commands qualify `-p` via `_helpers.project_cli_spec` when the session org differs from the config default.
- `fetch-task` / `api.fetch_task` infer the project from the first numeric task id when no project is given (`services/resolve.py:infer_project_from_tasks` via the `get_task` port method); name-only task specs still need an explicit project.

### Critical Implementation Details

#### Deleted Images Handling

CVAT allows frames to be marked as deleted (`data_meta.deleted_frames`), but annotation shapes for those frames **still exist** in the task data. This is handled in two places:

1. **Collection** (`_client/extractors.py`): Shapes are collected for ALL frames including deleted ones (needed for label counting, etc.)
2. **Partition** (`dataset_partition.py:125-127`): Deletion records are placed FIRST in the concat so `idxmax()` picks them in case of ties

**Bug fix history**: Previously, when an image had both annotations and deletion record with same `task_updated_date`, annotations won the tie. Fixed by reordering concat (see `test_deleted_image_with_annotations_in_same_task`).

#### Integration Testing

Integration tests require a running CVAT instance and are gated by `CVAT_INTEGRATION_HOST` env var. Test fixtures are in `tests/fixtures/cvat/coco8-dev/` (CVAT JSON format). The `FakeCvatApi` in `tests/fixtures/fake_cvat_api.py` provides in-memory CVAT simulation for unit tests.

**Running integration tests** (full lifecycle):

```bash
./scripts/integration_up.sh      # start CVAT + MinIO on fixed ports, seed test data
./scripts/integration_test.sh    # run all tests (handles env vars, disables xdist)
./scripts/integration_stop.sh    # tear down
```

`integration_test.sh` sets `CVAT_INTEGRATION_HOST`, `MINIO_ENDPOINT`, S3 credentials, and disables xdist automatically. Extra pytest args are forwarded: `./scripts/integration_test.sh -k upload`.

**Fixed ports**: CVAT API `9988`, MinIO API `9989`, MinIO console `9990`. Override with `--port` / `--minio-port` flags on `integration_up.sh`.

**Important caveats**:

- **No xdist**: parallel workers cause CVAT 429 rate-limiting and fixture ordering issues. `integration_test.sh` overrides `addopts` to disable `-n auto`.
- **Fresh state required**: upload integration tests create tasks in the seeded project. If you re-run tests against the same instance without re-seeding, `live-cvat` parametrized tests fail with `ValueError: Duplicate base task name`. Always tear down and restart between runs.

#### Task-by-Task Processing

`fetch` processes tasks individually (`fetch_one_task()`) and saves intermediate CSVs in `output/.tasks/task_{id}.csv` before merging. This allows resuming on failures and provides visibility into per-task data.

## Testing

```bash
uv run pytest                    # all tests (parallel)
uv run pytest tests/test_partition.py  # specific module
uv run pytest -k "deleted"       # by name pattern
uv run pytest -x                 # stop on first failure
```

**Test structure**:
- Unit tests mock `CvatApiPort` using `FakeCvatApi`
- Integration tests (`tests/integration/`) require `CVAT_INTEGRATION_HOST`
- Fixtures in `tests/fixtures/cvat/` contain real CVAT JSON snapshots
- **`tests/helpers.py`** holds shared builders (annotations, DataFrames, fakes); `conftest.py` holds fixtures only
- An autouse fixture in `conftest.py` sets `CVETA2_DISABLE_CACHE=true` for every test — cache tests opt back in explicitly
- **`tests/test_fetch_service.py`** is the canonical owner of the coco8 fetch scenarios
- **`tests/test_api.py`** covers the public `cveta2.*` workflow functions; **`tests/test_cli_parsing.py`** covers argparse wiring

## Configuration

Config loaded via `CvatConfig.load()` from:
1. Environment variables (`CVAT_HOST`, `CVAT_USERNAME`, `CVAT_PASSWORD`, `CVAT_ORGANIZATION`, `CVETA2_DATA_TIMEOUT`)
2. `~/.config/cveta2/config.yaml` (or `CVETA2_CONFIG`)
3. Built-in preset (`cveta2/presets/default.yaml`)

**Request timeouts**: opt-in via `CVETA2_DATA_TIMEOUT` env var or `cvat.request_timeout` config field (read timeout in seconds; connect timeout fixed at 10s). Applies to all CVAT HTTP requests (including client creation) and S3 operations. Unset or `0` = no timeout.

**Cache disable**: `CVETA2_DISABLE_CACHE=true` fully disables the task-annotation cache (no reads, writes, S3 backfill, or prune) — equivalent to always passing `--no-cache`.

**Sync roots**: the `sync_roots` config section (project name → `s3://bucket/prefix` or bare prefix) overrides the image download source for `s3-sync` and `fetch`; `s3-sync --root` is a one-run override. Upload always targets the project's own storage.

**Cache settings**: the `cache` config section holds global defaults + per-project overrides: `images_root` (fallback image-cache root when a project is absent from `image_cache`), `tasks_root` (local task-annotation cache root, default `~/.cache/cveta2/task_annotations`), `projects.<name>.ignored_prefix` (leading S3-key part stripped on local save instead of the full storage prefix — keeps more of the S3 hierarchy locally), `projects.<name>.task_cache_s3` (explicit S3 location for the shared task cache: `s3://bucket/prefix` or bare prefix in the project bucket; entries then live under `<prefix>/task_annotations/` without the `.cveta2_cache` segment). Configured interactively by `setup-cache`. The local image cache mirrors the S3 key layout below the effective storage prefix (`sync_roots` overrides the prefix; `ignored_prefix` skips less of the hierarchy). Cache dirs/files are created group-writable (0o775/0o664) for multi-user sharing. Nested CVAT frame names (`sub/img.jpg`) keep `image_name` as a basename; the full key is carried in the internal `frame_path` model field (kept in cache JSON, excluded from CSV) and used to build `s3_image_path`.

**Noninteractive mode**: Set `CVETA2_NO_INTERACTIVE=true` to disable all prompts (for CI).

**Error handling**: CVAT 5xx errors during fetch are handled per-task — failed tasks are skipped with a warning and the rest proceed. Set `CVETA2_RAISE_ON_FAILURE=true` to abort on first error instead.

## Important Files

- **CONTRIBUTING.md** - Style guide, linter setup, documentation rules
- **DATASET_FORMAT.md** - Output CSV format, data model reference
- **README.md** - User documentation (Russian)
- **pyproject.toml** - Dependencies, tool configs, import-linter contracts

## Common Tasks

**Add new command**:
1. Add the orchestration to `cveta2/services/` (pure, no prompts/`sys.exit`; raise `Cveta2Error`)
2. Create `cveta2/commands/mycommand.py` with `run_mycommand(args: argparse.Namespace)` — a thin adapter that resolves prompts, opens a client via `open_client()`, and calls the service
3. Expose it as a `cveta2.mycommand(...)` function in `cveta2/api.py` (no prompts; raise on missing settings)
4. Add subparser in `cveta2/cli.py`
5. Update README.md (Russian)

**Modify partition logic**:
1. Edit `cveta2/dataset_partition.py`
2. Add test case in `tests/test_partition.py`
3. Run `uv run pytest tests/test_partition.py tests/test_fetch_service.py`

**Update data models**:
1. Edit pydantic models in `cveta2/models.py`
2. Update `DATASET_FORMAT.md` if CSV columns change
3. Ensure tests in `tests/test_extractors.py` pass

## Pre-commit Hooks

The pre-commit pipeline runs: format → lint → import-linter → mypy → vulture → pytest → count-lines → build → lock.

**Always run before committing**:
```bash
uv run pre-commit run --all-files
```

If hooks modify files (ruff format), review changes and re-add them.

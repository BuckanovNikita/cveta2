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
- Never silently swallow exceptions. At minimum, log at `debug` level so failures are traceable. Use `warning` when the caller gets incomplete/degraded results.
- When skipping items in a loop due to errors, track which items were skipped and log a summary after the loop so the user knows results may be incomplete.
- Ruff enforces this: the `BLE001` rule bans broad `except` clauses. Do not suppress it with `# noqa`.

## Architecture

**Layered architecture** enforced by import-linter (see `pyproject.toml`):

```
cli → commands → client → _client
      ↓          ↓
   models, exceptions, config (foundation - no upward imports)
```

### Module Organization

- **`cveta2/cli.py`** - Argparse CLI entry point, dispatches to commands
- **`cveta2/commands/`** - Command implementations:
  - `fetch.py` - Fetch annotations from CVAT project
  - `upload.py` - Upload annotated dataset back to CVAT
  - `convert.py` - Bidirectional CSV ↔ YOLO conversion
  - `merge.py` - Merge multiple fetch outputs
  - `labels.py` - Manage project labels
  - `s3_sync.py` - Download images from S3
  - `setup.py` / `setup-cache` - Initial config and project cache setup
  - `ignore.py` - Mark tasks to skip during fetch
  - `doctor.py` - Diagnostic checks
  - `_task_selector.py` / `_helpers.py` - Shared internals
- **`cveta2/client.py`** - High-level `CvatClient` API (public interface)
- **`cveta2/_client/`** - Low-level CVAT SDK adapter (internal)
  - `sdk_adapter.py` - Wraps `cvat_sdk` with our DTOs
  - `extractors.py` - Converts CVAT shapes to `BBoxAnnotation`
  - `dtos.py` - Raw CVAT data transfer objects
  - `ports.py` - Protocol for CVAT API (enables test fakes)
  - `context.py` - API context management
  - `mapping.py` - Data mapping utilities
- **`cveta2/models.py`** - Pydantic data models (BBoxAnnotation with optional `confidence`, DeletedImage, etc.)
- **`cveta2/config.py`** - Config loading (YAML + env vars + presets)
- **`cveta2/dataset_partition.py`** - Core logic: splits annotations into dataset/obsolete/in_progress
- **`cveta2/image_downloader.py`** - S3 → local sync
- **`cveta2/image_uploader.py`** - Local → S3 upload (organizes into `YYYY-MM/` subfolders)
- **`cveta2/s3_types.py`** - `S3Client` Protocol (interface for S3 operations)
- **`cveta2/projects_cache.py`** - Local project metadata cache

### Key Data Flow

1. **Fetch**: `cli` → `commands/fetch.py` → `client.fetch_annotations()` → `_client/sdk_adapter.py` → CVAT API
   - Returns `ProjectAnnotations(annotations, deleted_images)`
   - Annotations converted to `BBoxAnnotation` by `extractors.py`
   - Result partitioned by `dataset_partition.py` into dataset/obsolete/in_progress CSV files

2. **Upload**: `commands/upload.py` → `client.create_upload_task()` + `client.upload_task_annotations()`
   - Reads CSV, uploads images to S3 (into `YYYY-MM/` subfolders), creates CVAT task, uploads annotations

3. **Convert**: `commands/convert.py` — `--to-yolo` exports CSV to YOLO format (images + labels), `--from-yolo` imports YOLO predictions back to CSV. Uses `PixelBox`/`YoloBox` NamedTuples for coordinate conversion.

4. **Partition Logic** (`dataset_partition.py`):
   - For each image, finds **latest task** by `task_updated_date` (comparing annotations + deletions)
   - If latest task is deletion → image goes to `obsolete`, added to `deleted_images`
   - Otherwise: completed tasks → `dataset` (latest) or `obsolete` (stale), non-completed → `in_progress`
   - **Important**: Deletion records are concatenated **before** annotation records to win ties (same date)

### Critical Implementation Details

#### Deleted Images Handling

CVAT allows frames to be marked as deleted (`data_meta.deleted_frames`), but annotation shapes for those frames **still exist** in the task data. This is handled in two places:

1. **Collection** (`_client/extractors.py`): Shapes are collected for ALL frames including deleted ones (needed for label counting, etc.)
2. **Partition** (`dataset_partition.py:125-127`): Deletion records are placed FIRST in the concat so `idxmax()` picks them in case of ties

**Bug fix history**: Previously, when an image had both annotations and deletion record with same `task_updated_date`, annotations won the tie. Fixed by reordering concat (see `test_deleted_image_with_annotations_in_same_task`).

#### Integration Testing

Integration tests require a running CVAT instance and are gated by `CVAT_INTEGRATION_HOST` env var. Test fixtures are in `tests/fixtures/cvat/coco8-dev/` (CVAT JSON format). The `FakeCvatApi` in `tests/fake_cvat_api.py` provides in-memory CVAT simulation for unit tests.

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

## Configuration

Config loaded via `CvatConfig.load()` from:
1. Environment variables (`CVAT_HOST`, `CVAT_USERNAME`, `CVAT_PASSWORD`, `CVAT_ORGANIZATION`)
2. `~/.config/cveta2/config.yaml` (or `CVETA2_CONFIG`)
3. Built-in preset (`cveta2/presets/default.yaml`)

**Noninteractive mode**: Set `CVETA2_NO_INTERACTIVE=true` to disable all prompts (for CI).

**Error handling**: CVAT 5xx errors during fetch are handled per-task — failed tasks are skipped with a warning and the rest proceed. Set `CVETA2_RAISE_ON_FAILURE=true` to abort on first error instead.

## Important Files

- **CONTRIBUTING.md** - Style guide, linter setup, documentation rules
- **DATASET_FORMAT.md** - Output CSV format, data model reference
- **README.md** - User documentation (Russian)
- **pyproject.toml** - Dependencies, tool configs, import-linter contracts

## Common Tasks

**Add new command**:
1. Create `cveta2/commands/mycommand.py` with `run_mycommand(args, cfg, client)`
2. Add subparser in `cveta2/cli.py`
3. Update README.md (Russian)

**Modify partition logic**:
1. Edit `cveta2/dataset_partition.py`
2. Add test case in `tests/test_partition.py`
3. Run `uv run pytest tests/test_partition.py tests/test_pipeline_integration.py`

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

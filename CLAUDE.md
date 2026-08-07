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
./scripts/mutation_test.sh --profile fast  # mutation testing gate (pre-commit subset)
./scripts/mutation_test.sh --profile full  # mutation testing gate (whole scope, pre-push)
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
  - `_helpers.py` - Shared internals (task-selector resolution lives in `fetch.py:_resolve_task_selector`)
- **`cveta2/api.py`** - Public workflow functions mirroring the CLI 1:1 (`fetch`, `upload`, `convert_*`, `merge`, `whats_new`, `s3_sync`, `get_labels`, `update_labels`, `task_*`), re-exported from `cveta2/__init__.py`. Never prompts — missing settings raise `MissingHostError` / `MissingCredentialsError`.
- **`cveta2/services/`** - Orchestration (no prompts, no `sys.exit`; raise `Cveta2Error`):
  - `fetch.py` - `fetch_project()` / `fetch_selected_tasks()` pipelines
  - `upload.py` - `upload_dataset()` + plan building / filtering helpers
  - `convert/{common,yolo,coco}.py` - CSV ↔ YOLO / COCO conversion
  - `merge.py` - `merge_datasets()`
  - `output.py` - CSV read/write, path enrichment
  - `resolve.py` - project resolution (`ORG/PROJECT` spec parsing, org switching, project-from-task inference) and `sync_roots` override
  - `whats_new.py` - cutoff computation
- **`cveta2/client.py`** - `CvatClient`, a thin composition of the `_client_ops` mixins (SDK-free; requires a context manager for remote calls, never prompts)
- **`cveta2/_client_ops/`** - The domain orchestration behind `CvatClient`, split into cohesive mixins. Same architecture layer as `client.py`, and SDK-free — no file here imports `cvat_sdk`:
  - `base.py` - `_ClientBase`: config, lazy API handle, context-manager lifecycle
  - `read.py` / `fetch.py` - project & task lookups, per-task fetch pipeline
  - `write.py` - task creation, annotation and issue upload, label patches
  - `task_ops.py` - mark-deleted, drop-label, delete, status transitions
  - `images.py` - S3 download orchestration
  - `session.py` - `TaskWriteSession`, memoizing one `data_meta` fetch per task
  - `shared.py` - `FetchContext` and the 5xx skip helper
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

## Mutation Testing

`./scripts/mutation_test.sh` runs mutmut over the modules in
`[tool.mutmut].only_mutate` and fails if any mutant survives unexplained.

**Two profiles**, defined in `[tool.cveta2.mutation.profiles]`:

```bash
./scripts/mutation_test.sh --profile fast   # pre-commit subset
./scripts/mutation_test.sh --profile full   # whole gated scope (pre-push)
./scripts/mutation_test.sh                  # whole scope, no filter
uv run pre-commit install --hook-type pre-push   # required once, for the full gate
```

`full` is an **empty glob list** on purpose. mutmut honours a cached verdict
only when no positional mutant name is given, so writing it as `"*"` would
re-execute every mutant on every push. `fast` accepts that cost for its subset
in exchange for skipping the rest.

**Scope is a ratchet.** A module joins `only_mutate` in the *same commit* that
drives it to zero unexplained survivors, so the hook is never red on `main`.
There is no "measured but ungated" tier: `mutmut results` walks every file in
`only_mutate` regardless of what the run filtered on, so a parked module with
survivors reddens the full profile immediately. Measure a candidate by
temporarily adding it and reverting before committing.

**Two-stage entry criterion.** `mutate_only_covered_lines` is off, so every
mutant on an *uncovered* line is an automatic survivor that says nothing about
assertion quality. Close line coverage first, then triage mutants. The real
disqualifier is mutmut's own `no tests` status (exit code 33), not the
`[tool.coverage.run] omit` list — that is a reporting setting mutmut never
consults.

**When the hook fails**, inspect with `uv run mutmut show <name>` or
`uv run mutmut browse`, then in preference order: strengthen a test (the
default), restructure the source so the mutant cannot exist, or — only when the
mutation genuinely cannot change behaviour — add it to
`[tool.cveta2.mutation.equivalent]` with a reason. The gate also fails on a
*stale* allowlist entry: mutmut renumbers mutants whenever a function changes,
so a justification cannot silently drift onto a different mutant. Keep the
allowlist small; at scale every refactor of a mutated function forces
re-triage.

Two anti-patterns, both of which produce brittle change-detector tests:

- Do not assert exact `yaml.safe_dump` / `json.dumps` output when the only
  reader parses it back — `safe_load` is blind to escaping, key order and flow
  style, so such a test breaks on any unrelated field addition.
- Do not write a test whose only purpose is killing a mutant on an internal
  expression that reaches a log message. Restructure the source instead.

### What actually gets mutated

Verified against the installed mutmut 3.7 source; several of these are
counter-intuitive and decide whether a module is worth gating at all.

- **Only code inside a top-level `FunctionDef`.** Module-level constants
  (`CSV_COLUMNS`, `_DIR_MODE`, `_HTTP_5XX_MIN`) produce no mutants. Moving a
  repeated literal to module level is therefore a legitimate way to remove a
  cluster of unkillable mutants.
- **Decorated functions and classes are skipped entirely, body included**
  (`file_mutation.py:281-293`), except a single bare
  `@staticmethod`/`@classmethod`. So `@property`, `@contextmanager`,
  `@dataclass`, `@field_validator` and `@s3_retry` yield nothing. Pydantic
  models declared by inheritance are *not* skipped, so plain validator
  functions wired by class-body assignment still get mutated.
- **f-strings are never mutated** — the string operator fires only on
  `cst.SimpleString`. Since this project logs exclusively via f-strings, log
  message text was never mutated; `do_not_mutate_patterns` now suppresses
  logger calls at every level, which removes the one remaining
  whole-argument-to-`None` mutant per call site.
- **A glob matching no mutant crashes the run** (`assert filtered_mutants`), so
  never name a zero-mutant module in a profile.

### Config notes that are easy to get wrong

- `pytest_add_cli_args` must keep `-n 0`; mutmut runs `pytest.main()` in each
  forked child and the global `addopts = [..., "-n", "auto"]` would otherwise
  spawn an xdist pool per mutant, which looks like a hang.
- `cache_invalidation_files` + `on_dependency_change = "rerun"` are
  load-bearing: mutmut keys a cached verdict on the *source* function's text,
  so without them a weakened test leaves the gate green on stale results. The
  corollary is that editing any file under `tests/` re-runs the entire scope.
- `mutate_only_covered_lines` must stay off — its coverage pre-pass leaves a
  half-imported numpy in `sys.modules` and the stats run then dies.
- **`only_mutate` and `do_not_mutate_patterns` are excluded from mutmut's own
  config fingerprint**, which hashes only pytest args, timeouts and the
  type-check command. Changing either therefore leaves a stale mutant tree:
  adding five modules to `only_mutate` once reported `0 files mutated, 6
  unmodified` and re-gated the old mutants as if nothing had changed.
  `scripts/mutation_config.py sync-scope` fingerprints those fields itself and
  wipes `mutants/` when they move, so this is handled automatically — but if
  you ever bypass `mutation_test.sh`, wipe `mutants/` by hand.
- `mutants/` is mutmut's working copy: gitignored, and excluded from mypy (two
  `cveta2` packages otherwise collide) and ruff.
- `mutation_test.sh` exports `PYTEST_DEBUG_TEMPROOT` into `mutants/`. By
  default every pytest run on the machine shares `/tmp/pytest-of-$USER`, and a
  concurrent session's cleanup can delete the `pytest-current` symlink out from
  under a mutant's forked child. The child then dies for reasons unrelated to
  the mutation and mutmut records it as *killed* — the gate lying in the unsafe
  direction. Observed while running several gates in parallel worktrees.

### Cost

~4.5s of fixed overhead per run, plus a throughput between ~120 mutants/second
over in-memory frames and ~50 for modules whose tests round-trip CSVs through
`tmp_path`. A fully cached run reports `0.00 mutations/second`.

At the current 4700 gated mutants, `full` takes ~63s and `fast` ~17s. Profile
membership is chosen to keep that gap worth having: putting *every* gated
module in `fast` once measured the same as `full`, i.e. the split bought
nothing. Keep `fast` under ~20s; when a newly gated module would push it past
that, leave it to `full`.

Triage, not runtime, is the real cost: each survivor needs a diff read and a
judgement call.

### Current scope

Every module worth mutating is gated — 27 modules, 4700 mutants, 98.4% killed,
77 allowlisted, zero unexplained. There is no ungated backlog left, so a new
module joining `cveta2/` should come with its own entry in `only_mutate` rather
than being added to a to-do list.

### Permanently out of scope

Two distinct reasons, which imply different things about whether the exclusion
could ever be lifted:

- **Zero mutable surface** — nothing to gate, ever: `_client/{ports,dtos,mapping}.py`,
  `_client_ops/{shared,session}.py`, `exceptions.py`, `client.py`, `_retry.py`,
  `_clearml/*`. `session.py` is a decorated dataclass whose four guards are all
  `@property`, so it generates no mutants at all.
- **Mutants exist but are low-signal plumbing already pinned by existing
  tests** — admission costs runtime for no new signal: `fs_utils.py` (its whole
  contract is the module-level `_DIR_MODE`/`_FILE_MODE`) and
  `_client/context.py`.
- **Adapters** — `cli.py` is ~640 `add_argument()` calls whose mutable content
  is help text and arguments that restate argparse defaults; `commands/*` is
  prompts, arg mapping and `sys.exit`. Note the reason is prompt/wiring
  density, *not* log-message density: message text was never mutated.

`config.py` and `api.py` were the two undecided cases; both were measured
(179 and 274 unexplained survivors) and are now gated. `api.py` needed no
allowlist entries at all — every one of its 274 survivors was a real test gap,
107 of them on functions no test executed.

## Pre-commit Hooks

The pre-commit pipeline runs: format → lint → import-linter → mypy → vulture → pytest → mutmut (fast profile) → count-lines → build → lock.

A second hook, `mutmut-full`, runs the whole gated mutation scope at **pre-push**.
It needs a one-time install:

```bash
uv run pre-commit install --hook-type pre-push
```

**Always run before committing**:
```bash
uv run pre-commit run --all-files
```

If hooks modify files (ruff format), review changes and re-add them.

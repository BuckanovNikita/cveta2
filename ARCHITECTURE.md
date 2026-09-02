# cveta2 architecture

The layer diagram and the rule that governs it live in `CLAUDE.md`; this file
is the map underneath it — which module owns what, how a command flows through
the layers, and the two behaviours that are easy to get wrong when touching
them. `CONTRIBUTING.md` covers the same ground in Russian, at overview depth.

## Module organization

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
  - `_bootstrap.py` - `open_client()`: single config load, host check, timeout setup — the only place *credentials* are prompted for
  - `interactive/` - every other prompt: project/task pickers, wizards, confirmations, questionary primitives
  - `_helpers.py` - Shared internals (task-selector resolution lives in `fetch.py:_resolve_task_selector`)
- **`cveta2/api.py`** - Public workflow functions, one per *data* command (`fetch`, `fetch_task`, `upload`, `convert_*`, `merge`, `whats_new`, `s3_sync`, `get_labels`, `update_labels`, `ignore`, `task_*`), re-exported from `cveta2/__init__.py`. The interactive-only commands (`setup`, `setup-cache`, `setup-clearml`, `doctor`) have no counterpart. Never prompts — missing settings raise `MissingHostError` / `MissingCredentialsError`.
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
  - `sdk_convert.py` - Opaque SDK objects → typed DTOs
- **`cveta2/_clearml/`** - Optional ClearML dataset publishing (isolated layer)
- **`cveta2/exceptions.py`** - `Cveta2Error` and its subclasses; every layer above raises these and the CLI turns them into a clean exit
- **`cveta2/models.py`** - Pydantic data models (BBoxAnnotation with optional `confidence`, DeletedImage, etc.)
- **`cveta2/config.py`** - Config loading (YAML + env vars + presets)
- **`cveta2/dataset_partition.py`** - Core logic: splits annotations into dataset/obsolete/in_progress
- **`cveta2/task_cache.py`** - Cache of completed-task annotations: local dir + shared S3 mirror, valid for as long as CVAT still calls the task `completed`
- **`cveta2/image_downloader.py`** - S3 → local sync; resolves a small batch of images by probing the key each CVAT frame name implies (`s3_utils.s3_object_exists`) and falls back to the whole-prefix listing only for what that misses
- **`cveta2/image_uploader.py`** - Local → S3 upload (organizes into `YYYY-MM/` subfolders)
- **`cveta2/s3_types.py`** - `S3Client` Protocol (interface for S3 operations)
- **`cveta2/s3_utils.py`** - S3 client construction, key helpers, the parallel transfer runner and the S3 retry predicate
- **`cveta2/fs_utils.py`** - Local filesystem writes under the shared-cache permission modes (`_DIR_MODE`/`_FILE_MODE`)
- **`cveta2/projects_cache.py`** - Local project metadata cache, keyed by organization (`organizations: [{slug, name, projects}]`; `""` slug = personal workspace)
- **`cveta2/_concurrency.py`** - `run_concurrent`, the one bounded fan-out every parallel site goes through, plus the process-wide `Workers` counts
- **`cveta2/_retry.py`** - retry mechanism (attempts, backoff, logging); the *predicates* deciding what is worth retrying live next to the calls they protect, in `_client/sdk_adapter.py` and `s3_utils.py`
- **`cveta2/upload_manifest.py`** - crash record of an in-flight upload, read by `upload --resume`

## Key data flow

1. **Fetch**: `cli`/`api.fetch` → `commands/fetch.py` (or `api.py`) → `services/fetch.py:fetch_project()` → `client.fetch_one_task()` per task → `_client/sdk_adapter.py` → CVAT API
   - Task selection scales with the request, not the project: `_client_ops/fetch.py:_select_tasks_for_fetch` retrieves each selector through `get_task` when all of them are numeric ids, and only walks the project task list otherwise — for a name selector, an id that turns out to name a task, a task belonging to another project, or an ignored id (all of which the listing path still owns, and all of which end in an error or a skip)
   - Completed tasks are served from `task_cache.py` whenever an entry exists (local `~/.cache/cveta2/task_annotations/`, backfilled from the project bucket's `<prefix>/.cveta2_cache/`); the live `completed` status is the whole freshness check, since a job moved back to annotation takes that status away. `--no-cache` / `--force` / `CVETA2_DISABLE_CACHE=true` override, full fetch prunes orphaned local entries
   - Returns `ProjectAnnotations(annotations, deleted_images)`
   - Annotations converted to `BBoxAnnotation` by `extractors.py`
   - Result partitioned by `dataset_partition.py` into dataset/obsolete/in_progress CSV files

2. **Upload**: `commands/upload.py` (or `api.upload`) → `services/upload.py:upload_dataset()` → `client.create_upload_task()` + `client.upload_task_annotations()`
   - A manifest is written to `~/.cache/cveta2/uploads/project_<id>/<fingerprint>.json` before CVAT is touched, and the task id recorded the instant it exists — `create_upload_task` splits the CVAT call in two (`create_task`, then `attach_task_data`) so there is a checkpoint between them. Removed on success.
   - `--resume` reads the manifest for *which* task, then asks CVAT what that task actually holds: frame count decides reuse / recreate / abort, a non-zero shape count means the annotations already landed (`put_task_shapes` appends, so a second pass would duplicate them), and issues are diffed by `(frame, message)`. `set_deleted_frames` and `update_job` are idempotent and simply redone.
   - Reads CSV, uploads images to S3 (into `YYYY-MM/` subfolders), creates CVAT task, uploads annotations
   - Label selection is frame-based: a selected label pulls in all annotations of its frames (co-occurring labels included and validated against project labels); `--labels all` selects every dataset label plus unannotated frames (a literal dataset label named `all` wins over the shortcut)
   - Rows with `issue_state="new"` and non-empty `issue_text` become open CVAT issues **attached to the row's bbox**; rows with issue text but no complete bbox are skipped with a warning (no full-frame issues)
   - A CSV whose rows are all `instance_shape="deleted"` is a valid upload: the label step is skipped and only deleted frames are pushed

3. **Convert**: `commands/convert.py` (or `api.convert_*`) → `services/convert/`: `convert_to_yolo` exports CSV to YOLO format (images + labels), `convert_from_yolo` imports YOLO predictions back to CSV, `convert_to_coco` exports COCO detection format. Uses `PixelBox`/`YoloBox` NamedTuples for coordinate conversion.

4. **Partition Logic** (`dataset_partition.py`):
   - For each image, finds **latest task** by `task_id` (comparing annotations + deletions). Ids are monotone with task creation and never move; `task_updated_date` does — a project label edit rewrites it on every task at once
   - If latest task is deletion → image goes to `obsolete`, added to `deleted_images`
   - Otherwise: completed tasks → `dataset` (latest) or `obsolete` (stale), non-completed → `in_progress`
   - **Completed** is read from `job_stage`/`job_state`, not from a task-level field: `completed_task_ids()` requires *every* row of the task — deletion records included — to sit on `acceptance`/`completed`, which is how CVAT itself derives a task's status from its jobs
   - Deletion records are concatenated **before** annotation records to win same-task ties; see [Deleted images handling](#deleted-images-handling)

## Project specs and organizations

- Every project spec (CLI `-p`, API `project=`) accepts an id, a name, or `ORG/PROJECT` (`/PROJECT` = personal workspace). The org prefix calls `client.set_organization()`, switching the session org for all subsequent CVAT calls (`services/resolve.py:split_project_spec` / `apply_project_org`).
- The interactive picker (`commands/interactive/entities.py:select_project`) pages projects by organization — first page is the config org — and switches the session org on selection. Echoed re-run commands qualify `-p` via `_helpers.project_cli_spec` when the session org differs from the config default.
- `fetch-task` / `api.fetch_task` infer the project from the first numeric task id when no project is given (`services/resolve.py:infer_project_from_tasks` via the `get_task` port method); name-only task specs still need an explicit project.
- A numeric project spec is named from the local projects cache when it holds the id, otherwise through the `get_project` port method, never by listing the organization; an id nobody owns falls back to the id as the display name (`services/resolve.py:_project_display_name`). A name spec resolves to CVAT's own spelling of the name (`find_project_by_name`, case-insensitive), so config sections keyed by project name match however the user typed it. `client.detect_project_cloud_storage` is memoized per project for the client's lifetime and dropped on `set_organization`.

## Deleted images handling

CVAT allows frames to be marked as deleted (`data_meta.deleted_frames`), but annotation shapes for those frames **still exist** in the task data. This is handled in two places:

1. **Collection** (`_client/extractors.py`): Shapes are collected for ALL frames including deleted ones (needed for label counting, etc.)
2. **Partition** (`dataset_partition.py`): Deletion records are placed FIRST in the concat, so the `sort_values` + `drop_duplicates(keep="first")` in `_latest_row_per_image` picks them in case of ties

Two different tasks can no longer tie, so the only tie left is inside one task: a frame it annotated and also marked deleted. That is the case the concat order settles (see `test_deleted_image_with_annotations_in_same_task`, and `test_deletion_wins_tie_in_a_frame_too_large_for_a_stable_sort` for why the row position is an explicit sort key rather than assumed sort stability).

## Nested frame names

Nested CVAT frame names (`sub/img.jpg`) keep `image_name` as a basename; the
full key is carried in the internal `frame_path` model field — kept in the task
cache JSON, excluded from the CSV — and used to build `s3_image_path`. The
local image cache mirrors the S3 key layout below the effective storage prefix
(`sync_roots` overrides the prefix, `cache.projects.<name>.ignored_prefix`
skips less of the hierarchy); see README.md for the user-facing description.

## Task-by-task processing

`fetch` reads one task at a time (`fetch_one_task()`), but the tasks themselves
run concurrently through `run_concurrent(..., max_workers=Workers.cvat)`; results
are merged positionally so the output does not depend on completion order.

Each task's rows are written to `output/.tasks/task_{id}.csv` as they arrive.
That directory is **removed after the merge** unless `--save-tasks` is given, and
nothing ever reads it back — it is a debugging artefact, not a resume point. The
only `--resume` in the project belongs to `upload`, and it reads its manifest
from `~/.cache/cveta2/uploads/`, not from here.

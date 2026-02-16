# Agent Documentation

Short descriptions of project internals and implicit design decisions.

## Package structure

```
cveta2/
  __init__.py   - public API re-exports: CvatClient, fetch_annotations, AnnotationRecord, BBoxAnnotation, DeletedImage, ImageWithoutAnnotations, ProjectAnnotations, partition_annotations_df, PartitionResult, CSV_COLUMNS, Cveta2Error, ProjectNotFoundError, TaskNotFoundError, InteractiveModeRequiredError
  models.py     - Pydantic models: BBoxAnnotation, DeletedImage, ImageWithoutAnnotations, ProjectAnnotations; AnnotationRecord discriminated union (BBoxAnnotation | ImageWithoutAnnotations, discriminator=instance_shape); CSV_COLUMNS tuple defining the canonical CSV column order; ProjectAnnotations.to_csv_rows() method
  exceptions.py - Custom exception hierarchy: Cveta2Error (base), ProjectNotFoundError, TaskNotFoundError, InteractiveModeRequiredError
  dataset_partition.py - partition_annotations_df(): pandas-based partitioning of annotation DataFrame into dataset/obsolete/in_progress; PartitionResult dataclass; dates parsed via pd.to_datetime(utc=True) for robust comparison
  config.py     - CvatConfig pydantic model; loads/merges preset < config file < env; get_config_path(config_path?) — single source for config file path (used by doctor and all section load/save); ImageCacheConfig, IgnoreConfig, UploadConfig; load_image_cache_config(), save_image_cache_config(), load_ignore_config(), save_ignore_config(), load_upload_config() implemented via _load_section() / _save_section() (parse_fn / serialize_fn per section); get_projects_cache_path(); is_interactive_disabled() / require_interactive(); _load_preset_data() loads bundled preset from cveta2/presets/default.yaml
  image_downloader.py - CloudStorageInfo pydantic model; parse_cloud_storage() extracts bucket/prefix/endpoint from CVAT SDK cloud storage object; ImageDownloader class downloads images from S3 via boto3 into a flat target directory (no subdirs); S3Syncer class lists all objects under an S3 prefix and downloads missing ones locally (never deletes, never uploads); _list_s3_objects() lists S3 objects with prefix stripping; _download_one_s3() shared download helper with tenacity retry; DownloadStats pydantic model (downloaded/cached/failed/total); auto-detects cloud_storage_id from task source_storage; _build_s3_key() handles prefix logic; tqdm progress bar
  projects_cache.py - YAML cache of project id/name list (load_projects_cache, save_projects_cache); path next to config (projects.yaml)
  client.py     - CvatClient class (list_projects, resolve_project_id, fetch_annotations, download_images, detect_project_cloud_storage, sync_project_images, create_upload_task; usable as context manager for connection reuse) + fetch_annotations() DataFrame wrapper; _SdkClientFactory Protocol for typed client_factory parameter; all paths go through CvatApiPort for annotations; fetch_annotations() accepts optional task_selector (list[int|str]) to fetch specific tasks by ID or name via _resolve_task_selectors(); download_images() uses raw SDK client directly (not CvatApiPort) for cloud storage detection + delegates to ImageDownloader; sync_project_images() detects cloud storage then delegates to S3Syncer; create_upload_task() creates a CVAT task backed by cloud storage images with segment_size controlling job size; _require_sdk() shared helper for methods needing the raw SDK; tqdm progress bar on task loop
  image_uploader.py - S3Uploader class uploads images to S3, skipping already-existing files; UploadStats pydantic model (uploaded/skipped_existing/failed/total); resolve_images() searches directories for image files by name; reuses CloudStorageInfo, _build_s3_key, _list_s3_objects, _s3_retry from image_downloader.py
  presets/      - bundled preset configurations
    __init__.py - package marker
    default.yaml - default preset: cvat.host = http://localhost:8080 (no credentials); upload.images_per_job = 100
  _client/      - internal implementation details split from client.py
    dtos.py     - frozen dataclass DTOs for CVAT API responses (RawFrame, RawShape, RawTrack, RawTask, RawLabel, etc.)
    ports.py    - CvatApiPort Protocol defining the API boundary; the single seam for mocking
    sdk_adapter.py - SdkCvatApiAdapter: CvatApiPort implementation wrapping an open cvat_sdk client; thin stateless converter (SDK objects in, DTOs out); tenacity retry with exponential backoff on all public methods; _extract_updated_date and _extract_creator_username use getattr for SDK version compat (intentional exception to style rule, documented inline)
    context.py  - _TaskContext + extraction constants; frames typed as dict[int, RawFrame]; get_frame() and get_label_name() for extractors; from_raw(task, data_meta, label_names, attr_names) classmethod builds context from DTOs
    mapping.py  - helper functions for label/attribute mapping; takes typed DTOs (RawLabel, RawAttribute)
    extractors.py - shape conversion into BBoxAnnotation models; takes typed DTOs (RawShape); only direct shapes processed (tracks intentionally skipped)

  commands/     - CLI command implementations, split from cli.py
    __init__.py - package marker
    _helpers.py - shared CLI helpers: load_config(), require_host(), resolve_project_from_args(), select_project_tui(), write_dataset_and_deleted(), write_df_csv(), write_deleted_txt(), read_dataset_csv()
    setup.py    - run_setup(): interactive wizard for CVAT credentials and core settings (host, org, auth); run_setup_cache(): interactive per-project image cache directory setup for all known projects (fetches project list from CVAT if cache is empty); _ensure_projects_list() helper loads or fetches projects
    fetch.py    - run_fetch(): fetch all project annotations + download images; run_fetch_task(): fetch annotations for selected task(s), uses write_dataset_and_deleted() for output; _resolve_project() uses resolve_project_from_args() and select_project_tui() from _helpers; _download_images(), _write_output(); _resolve_task_selector() + select_tasks_tui for multi-task selection; _resolve_images_dir() for image cache resolution; _resolve_output_dir() for overwrite prompt; _write_partition_result() for partitioned CSV/TXT export
    ignore.py   - run_ignore(): manage per-project task ignore lists (add/remove/list); reads and writes the `ignore` section of config YAML
    merge.py    - run_merge(): merge two dataset CSVs (old + new) with conflict resolution (new-wins or by-time); _propagate_splits() copies split values from old to merged rows with null split; warns when old has no split data or when both sides have non-null split for common images
    s3_sync.py  - run_s3_sync(): sync images from S3 cloud storage to local cache for configured projects
    doctor.py   - run_doctor(): health checks for config, AWS credentials, and image cache group permissions; check_config(), check_aws_credentials(), check_cache_permissions()
  cli.py        - slim argparse CLI entry point; CliApp class with parser definitions (fetch, fetch-task, setup, setup-cache, s3-sync, upload, merge, ignore, doctor) and dispatch to commands/ modules; shared fetch args extracted into _add_common_fetch_args(); all command logic lives in commands/
  __main__.py   - enables `python -m cveta2`
main.py         - thin backwards-compat wrapper delegating to cveta2.cli.main()
```

## Config resolution

Priority: preset < config file < env vars. No CVAT settings/credentials on CLI. Env: `CVAT_HOST`, `CVAT_ORGANIZATION`, `CVAT_TOKEN`, `CVAT_USERNAME`, `CVAT_PASSWORD`. Config file path: `CVETA2_CONFIG` or default `~/.config/cveta2/config.yaml`. Bundled preset in `cveta2/presets/default.yaml` provides lowest-priority defaults (host = `http://localhost:8080`). If host is missing after all merges, CLI suggests running `cveta2 setup` or setting env. Config file uses YAML with `cvat` mapping to `CvatConfig` fields. Organization is applied via `client.organization_slug` after client creation.

## Image cache config

Config YAML has an `image_cache` top-level section — a flat mapping of project name to absolute local directory path:
```yaml
image_cache:
  coco8-dev: /mnt/disk01/data/project_coco_8_dev
  my-other-project: /home/user/datasets/other
```
Images are saved directly into the mapped directory (e.g. `/mnt/disk01/data/project_coco_8_dev/image.jpg`) — **no subdirectories are created**. `ImageCacheConfig` pydantic model wraps `dict[str, Path]`; `get_cache_dir(project_name)` returns `Path | None`; `set_cache_dir()` adds/updates. `load_image_cache_config()` and `save_image_cache_config()` read/write only the `image_cache` section, preserving the rest of the YAML. `CvatConfig.save_to_file()` accepts an optional `image_cache` parameter to persist both sections atomically.

## CVAT image storage and download flow

### CVAT cloud storage data model

CVAT stores images in **S3-compatible cloud storages** (AWS S3, MinIO, etc.), registered as CVAT entities via the REST API. Each cloud storage object exposed by the CVAT SDK has the following fields relevant to image downloading:

- `id` (int) — unique identifier of the cloud storage in CVAT.
- `resource` (str) — the S3 bucket name.
- `specific_attributes` (str) — URL-encoded query string containing `prefix` (path prefix inside the bucket, e.g. `project1/images`) and `endpoint_url` (S3-compatible endpoint, e.g. `http://minio:9000` for a local MinIO instance). Parsed via `urllib.parse.parse_qs()`.

Cloud storage is retrieved via the SDK: `sdk_client.api_client.cloudstorages_api.retrieve(cloud_storage_id)` which returns the raw cloud storage object. `parse_cloud_storage()` in `image_downloader.py` extracts `bucket`, `prefix`, and `endpoint_url` into a `CloudStorageInfo` pydantic model using `getattr` (SDK objects are opaque and vary across versions).

Tasks reference their cloud storage via the `source_storage` field on the CVAT task object. This field contains `cloud_storage_id` (the integer ID linking to the cloud storage entity). Depending on CVAT SDK version, `source_storage` may be a `dict` (with key `"cloud_storage_id"`) or a typed SDK model (with attribute `cloud_storage_id`). `_detect_cloud_storage()` handles both variants.

Frame names from `data_meta.frames` correspond to S3 object keys relative to the bucket root and may or may not include the cloud storage prefix depending on CVAT version. `_build_s3_key()` handles this: if `frame_name` already starts with `prefix`, it is used as-is; otherwise `prefix/frame_name` is constructed; if prefix is empty, just `frame_name`.

### Download pipeline (end-to-end)

Image download is a separate step after annotation fetching, reusing the same `CvatClient` SDK connection. The pipeline in `ImageDownloader.download()`:

1. **Collect frames** — gather unique `(image_name, task_id)` pairs from `annotations.annotations` (which contains both `BBoxAnnotation` and `ImageWithoutAnnotations` records). Deleted images are excluded.
2. **Partition cached** — for each frame, check if `target_dir/image_name` already exists on disk. If so, increment `stats.cached` and skip. Group remaining frames by `task_id`.
3. **Resolve cloud storages** — for each task with pending downloads: call `sdk_client.tasks.retrieve(task_id)`, read `source_storage`, extract `cloud_storage_id`. Then `cloudstorages_api.retrieve(cs_id)` → `parse_cloud_storage()` → `CloudStorageInfo`. Results are cached per `cloud_storage_id` within the session. Tasks without `source_storage` are counted as `failed`.
4. **Create S3 clients** — one `boto3.Session().client("s3", endpoint_url=...)` per unique `(endpoint_url, bucket)` pair. S3 credentials come from the standard boto3 chain (`~/.aws/credentials`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars, IAM roles). No S3 credentials are stored in the cveta2 config.
5. **Execute downloads** — for each pending frame: construct the S3 key via `_build_s3_key(prefix, image_name)`, call `s3.get_object(Bucket=bucket, Key=s3_key)`, write bytes to `target_dir/image_name`. Each download is retried up to 3 times with exponential backoff via tenacity. Progress displayed via tqdm.

### Image path resolution in CLI

The `_resolve_images_dir()` helper in `commands/fetch.py` resolves the target directory for image downloads with this priority chain:

1. `--no-images` flag → skip download entirely (return None).
2. `--images-dir` CLI argument → use this path directly (highest priority override).
3. `image_cache` config mapping → look up `project_name` in `ImageCacheConfig.projects`.
4. **Interactive mode** → prompt the user for a path, then save it to config for future runs.
5. **Non-interactive mode** → exit with error instructing user to set `--images-dir`, `--no-images`, or configure `image_cache.<project_name>` in config.

## Non-interactive mode

Set `CVETA2_NO_INTERACTIVE=true` (case-insensitive) to disable all interactive prompts. When set, any operation that would require user input raises `RuntimeError` with a hint about which CLI flag or env var to use instead. The variable can be unset or empty — defaults to interactive mode enabled. Guarded locations: `cveta2 setup` and `cveta2 setup-cache` (entire commands), TUI project selection in `fetch` (use `--project`), credential prompts in `ensure_credentials()` (use `CVAT_TOKEN` / `CVAT_USERNAME` + `CVAT_PASSWORD`), image cache path prompt in `fetch` (use `--images-dir` / `--no-images` or configure `image_cache` in config). The output-dir overwrite prompt silently overwrites in non-interactive mode instead of raising. In non-interactive mode, if image cache path is not configured for the project, `fetch` **fails with error** (does not silently skip). Helper functions: `is_interactive_disabled()` and `require_interactive(hint)` in `config.py`.

## CLI commands

- `setup` — interactive wizard that prompts for host, organization, and auth (token or username/password). Saves credentials to `~/.config/cveta2/config.yaml` via `CvatConfig.save_to_file()`. Prefills defaults from existing config if present. Optional `--config` to override config path.
- `setup-cache` — interactive wizard that iterates over all known CVAT projects and prompts for an image cache directory for each. Shows current path if already configured; press Enter to skip/keep. If the projects cache is empty, connects to CVAT to fetch the project list first. Saves updated `image_cache` section via `save_image_cache_config()`. Optional `--config` to override config path.
- `fetch` — fetches **all** bbox annotations and deleted images from a CVAT project, splits them into three CSVs, and optionally downloads project images from S3 cloud storage. Arguments:
  - `--project` / `-p` — project ID (number) or project name; if omitted, TUI shows cached project list with arrow-key selection and search filter; "↻ Обновить список" rescans CVAT and refreshes cache.
  - `--output-dir` / `-o` (required) — directory for output files: `dataset.csv`, `obsolete.csv`, `in_progress.csv`, `deleted.txt`.
  - `--raw` — additionally save unprocessed full DataFrame as `raw.csv` in the output dir.
  - `--completed-only` — process only tasks with status "completed" (in_progress.csv will be empty).
  - `--no-images` — skip downloading images from S3 cloud storage entirely.
  - `--images-dir` — override the image cache directory for this run (takes precedence over `image_cache` config mapping; path used directly, no subdirectories created).

- `fetch-task` — fetches bbox annotations for **specific task(s)** in a project. Unlike `fetch`, does not partition into dataset/obsolete/in_progress — writes a single `dataset.csv` and `deleted.txt` into the output directory. Arguments:
  - `--project` / `-p` — same as `fetch`.
  - `--task` / `-t` — task ID or name. Can be repeated (`-t 42 -t 43`). Numeric values match by task ID first, then by name; non-numeric strings match by name (case-insensitive). If passed without a value (`-t` alone) or omitted entirely, shows interactive TUI with checkbox multi-select (with search filter). Raises `TaskNotFoundError` if any selector doesn't match.
  - `--output-dir` / `-o` (required) — directory for output files: `dataset.csv`, `deleted.txt`.
  - `--completed-only`, `--no-images`, `--images-dir` — same as `fetch`.

- `s3-sync` — syncs all images from S3 cloud storage to local cache for every project configured in `image_cache`. Lists all objects under each project's cloud storage prefix and downloads those missing locally. Never deletes from S3 or syncs in reverse. Arguments:
  - `--project` / `-p` — sync only this project (name must exist in `image_cache` config). If omitted, syncs all configured projects.
  - Flow: loads `image_cache` from config → for each project resolves project ID via CVAT → gets project tasks → detects cloud storage from first task with `source_storage` → lists S3 objects under prefix → downloads missing files to the configured cache directory. Continues to next project on errors (project not found, no cloud storage).

- `ignore` — manage per-project task ignore lists. Ignored tasks are always treated as in-progress and skipped during `fetch`. Arguments:
  - `--project` / `-p` (required unless `--list`) — project name (as used in config).
  - `--add TASK_ID [TASK_ID ...]` — add task ID(s) to the ignore list.
  - `--remove TASK_ID [TASK_ID ...]` — remove task ID(s) from the ignore list.
  - `--list` — list ignored tasks for **all** projects. Does not require `--project` or a CVAT connection; reads only the local config. Output is grouped by project name with task id, name, and description.
  - If neither `--add`, `--remove`, nor `--list` is given, opens interactive TUI for the selected project.
  - `--add`, `--remove`, and `--list` are mutually exclusive.

- `upload` — creates a CVAT task from `dataset.csv`: reads the CSV, filters by class labels interactively, uploads images directly to S3 (skipping existing), and creates one task with multiple jobs (controlled by `segment_size`). Arguments:
  - `--project` / `-p` — project ID or name; if omitted, interactive TUI selection.
  - `--dataset` / `-d` (required) — path to `dataset.csv` produced by `fetch`.
  - `--in-progress` — path to `in_progress.csv`; images listed there are excluded from upload.
  - `--image-dir` — additional directory to search for image files on disk.
  - `--name` — task name; if omitted, prompted interactively.
  - Flow: read dataset.csv → read in_progress.csv (optional) → interactive `questionary.checkbox` for `instance_label` filtering → prompt task name → resolve image files on disk (search in `--image-dir` + project cache from `image_cache` config) → detect project cloud storage → upload missing images to S3 via `S3Uploader` → create CVAT task via `create_upload_task()` with `segment_size` from `UploadConfig` → log task URL.
  - Images per job (`segment_size`) controlled by `upload.images_per_job` in config (default 100). CVAT automatically splits the task into jobs of that size.
  - Always requires interactive mode (class selection is mandatory).

- `merge` — merges two dataset CSVs (`--old` and `--new`) into one output CSV. Images unique to either side are kept; for images in both, `--new` wins by default. Arguments:
  - `--old` (required) — path to the old (existing) dataset CSV.
  - `--new` (required) — path to the new (freshly downloaded) dataset CSV.
  - `--output` / `-o` (required) — path for the merged output CSV.
  - `--deleted` — path to `deleted.txt`; listed images are excluded from output.
  - `--by-time` — for conflicting images, compare `task_updated_date` and keep the more recent side (instead of always preferring new).
  - **Split propagation**: after merging, the `split` field from the old dataset is propagated to merged rows where `split` is null. This preserves manually assigned splits (`train`/`val`/`test`) across re-downloads. Warnings are logged when: (a) the old dataset has no `split` data at all; (b) both datasets have non-null `split` for the same common images (the winning side's value is kept).

## Ignore config

Config YAML has an `ignore` top-level section — a mapping of project name to a list of task IDs to ignore:
```yaml
ignore:
  my-project:
    - 123
    - 456
```
`IgnoreConfig` pydantic model wraps `dict[str, list[int]]`; `get_ignored_tasks(project_name)` returns `list[int]`; `add_task()` / `remove_task()` modify the list. `load_ignore_config()` and `save_ignore_config()` read/write only the `ignore` section, preserving the rest of the YAML. During `fetch`, ignored tasks are skipped entirely (not fetched from CVAT). A warning listing each skipped task's ID, name, and updated date is logged by `CvatClient._fetch_annotations()` when tasks match the ignore set. `CvatClient.fetch_annotations()` accepts `ignore_task_ids: set[int] | None` to filter tasks at the API level.

## Upload config

Config YAML has an `upload` top-level section:
```yaml
upload:
  images_per_job: 100
```
`UploadConfig` pydantic model wraps `images_per_job: int`. `load_upload_config()` reads the section; defaults to 100 if not present. The preset also includes `upload.images_per_job: 100`.

## Logging levels

- **INFO** — file save confirmations (`Annotations CSV saved`, `Deleted images list saved`, `Config saved`), interactive prompts, cache status messages, image download summary.
- **DEBUG** — API result summaries (project info, task counts, annotation/deleted/without-annotations counts, processing task progress), full JSON to stdout, API structure dumps (project, tasks, data_meta, annotations).
- **TRACE** — raw API object dumps (individual shapes, frames, deleted_frames, labels, attributes), cloud storage details per task.

## Data model notes

- `AnnotationRecord` — Pydantic discriminated union (`Annotated[BBoxAnnotation | ImageWithoutAnnotations, Discriminator("instance_shape")]`). `BBoxAnnotation` has `instance_shape="box"`, `ImageWithoutAnnotations` has `instance_shape="none"`. Both share `image_name`, `task_id`, `frame_id` and implement `to_csv_row()`.
- `BBoxAnnotation` includes task metadata (`task_id`, `task_name`, `task_status`, `task_updated_date`), source metadata (`created_by_username`, `source`, `annotation_id`), frame metadata (`frame_id`, `subset`, image size), and dataset metadata (`split`).
- `split` field (`Split | None`, default `None`) — our convention for dataset splits (`train`/`val`/`test`). Semantically equivalent to CVAT's `subset` but named differently by project convention. Filled with `None` on download, ignored on upload. The `Split` type alias is `Literal["train", "val", "test"]` defined in `models.py` and re-exported from `__init__.py`.
- `BBoxAnnotation.to_csv_row()` serializes `attributes` as a JSON string (`ensure_ascii=False`) so non-ASCII attribute values remain readable in CSV.
- `ImageWithoutAnnotations` — frames with no bbox annotations; included in CSV via `to_csv_row()` with None for bbox/annotation fields.
- `ProjectAnnotations` contains `annotations: list[AnnotationRecord]` (single list holding both `BBoxAnnotation` and `ImageWithoutAnnotations`) and `deleted_images: list[DeletedImage]`.
- `DeletedImage` — record of a deleted frame: `task_id`, `task_name`, `task_status`, `task_updated_date`, `frame_id`, `image_name`.
- `DownloadStats` — result counters for an image download run: `downloaded`, `cached`, `failed`, `total`.

## CSV partitioning logic (`dataset_partition.py`)

`partition_annotations_df(df, deleted_images)` partitions the full annotation DataFrame into three parts:

1. For each `image_name`, the **latest task** (max `task_updated_date`) is found across both df rows and `deleted_images`.
2. If the image is **deleted in its latest task** → all rows for that image go to **obsolete**, filename goes to `deleted_names`.
3. Otherwise: rows from non-completed tasks → **in_progress**; rows from the latest completed task → **dataset**; rows from older completed tasks → **obsolete**.

## API abstraction and testability

`CvatClient` has a **single code path** for annotation logic (`_fetch_annotations` static method) that works through `CvatApiPort` with typed DTOs. When `api` is injected (tests), the provided implementation is used directly. When `api` is `None` (production), `CvatClient` opens an SDK client via `client_factory` and wraps it in `SdkCvatApiAdapter` on the fly (via `_open_sdk_adapter` context manager), so the same `_fetch_annotations` code runs in both cases. All CVAT SDK interaction is isolated inside `SdkCvatApiAdapter`; no other module imports `cvat_sdk` (except `client.py` which imports `make_client` as the default factory). `SdkCvatApiAdapter` accepts an already-opened SDK client; `CvatClient` owns the client lifecycle. The DTOs are frozen dataclasses — easy to construct in test fixtures without any SDK dependency.

## Test fixtures (CVAT)

- **Layout**: `tests/fixtures/cvat/<project_name>/` contains `project.json` (id, name, labels) and `tasks/<task_id>_<slug>.json` (task meta, data_meta, annotations). JSON shape mirrors `_client/dtos.py` (RawTask, RawDataMeta, RawAnnotations, etc.).
- **Generator**: `scripts/export_cvat_fixtures.py` — uses only cvat_sdk (no cveta2 client). Reads `CVAT_HOST`, `CVAT_USERNAME`, `CVAT_PASSWORD` from env; `--project`, `--output-dir`. Fetches project by name, then for each task retrieves data_meta and annotations, converts to JSON-serializable dicts, writes to output dir. Do not import cveta2._client so fixtures are independent of library under test.
- **Loader**: `tests/fixtures/load_cvat_fixtures.py` — `load_cvat_fixtures(project_dir)` reads `project.json` and all `tasks/*.json`, returns `(RawProject, list[RawTask], list[RawLabel], dict[task_id, (RawDataMeta, RawAnnotations)])` using `cveta2._client.dtos`. Used by tests and by `FakeCvatApi`.
- **FakeCvatApi**: `tests/fixtures/fake_cvat_api.py` — implements `CvatApiPort` protocol, backed by `LoadedFixtures` NamedTuple (canonical definition in `fake_cvat_project.py`, imported everywhere else; fields: project, tasks, labels, task_data). Injected into `CvatClient(cfg, api=FakeCvatApi(fixtures))` for integration tests without SDK.
- **Tests**: `tests/test_cvat_fixtures.py` — loads coco8-dev fixtures, runs name-based consistency checks per task (e.g. task "all-removed" → every frame in deleted_frames; "normal" → at least one frame not deleted). No CvatClient; assertions on DTOs only. Task name → assertion registry: normal, all-empty, all-removed, zero-frame-empty-last-removed, all-bboxes-moved, all-except-first-empty, frames-1-2-removed.
- **Fake projects**: `tests/fixtures/fake_cvat_project.py` — build fake projects from base fixtures (e.g. coco8-dev) for tests. `FakeProjectConfig` (pydantic): `task_indices` (which base tasks, in order; can repeat), or `count` + random sampling; `task_id_order` ("asc" | "random"); `task_names` ("keep" | "random" | "enumerated" | list); `task_statuses` ("keep" | "random" | list); `seed` for reproducibility. `build_fake_project(base_fixtures, config)` returns the same `(RawProject, list[RawTask], list[RawLabel], task_id -> (RawDataMeta, RawAnnotations))` structure. `task_indices_by_names(base_tasks, ["normal", "all-removed"])` resolves names to indices. Tests in `tests/test_fake_cvat_project.py`.
- **Shared fixtures**: `tests/conftest.py` — session-scoped `coco8_fixtures`, `coco8_label_maps`, `coco8_tasks_by_name` for use across all test modules.
- **Pipeline tests**: `test_mapping.py` (label/attribute mapping), `test_extractors.py` (_collect_shapes unit tests), `test_partition.py` (partition_annotations_df), `test_pipeline_integration.py` (full pipeline via FakeCvatApi + CvatClient).
- **Image download tests**: `test_image_downloader.py` (unit tests with fake SDK and S3 clients — flat saving, caching, deleted images filtering, S3 key construction, stats; also S3Syncer tests — _list_s3_objects, full sync, skip cached, empty bucket, never deletes local files), `test_image_cache_config.py` (load/save/get/set of ImageCacheConfig), `test_cli_images.py` (CLI integration: --no-images, --images-dir, non-interactive error, configured path), `test_cli_s3_sync.py` (CLI integration: s3-sync with all projects, single project, no image_cache error, unknown project error, continues on resolve failure), `test_preset_config.py` (priority: preset < user config < env).

## Dev tools (scripts/)

- `scripts/upload_dataset_to_cvat.py` — creates a CVAT project and several tasks from a dataset YAML (e.g. coco8). Reads `path`, `train`, `val`, `names`; creates one project with labels from `names` and N tasks each with the same images (train+val). Uses `cveta2.config.CvatConfig` and cvat_sdk directly (no CvatApiPort). Run from repo root: `uv run python scripts/upload_dataset_to_cvat.py [--yaml path] [--project name] [--tasks N]`.
- `scripts/export_cvat_fixtures.py` — exports a CVAT project to JSON fixtures for tests. Uses only cvat_sdk; credentials via env. See "Test fixtures (CVAT)" above and `scripts/README.md`.
- `scripts/clone_project_to_s3.py` — clones a CVAT project, downloading images from the source and re-uploading them to an S3 cloud storage bucket, then creates a new CVAT project with identical labels/tasks/annotations pointing at the cloud storage files. Used to set up S3-backed test projects. CVAT creds from config, S3 creds from boto3 default chain. Run: `uv run python scripts/clone_project_to_s3.py --source <name> --dest <name> --cloud-storage-id <id>`.

## Implicit decisions

- **Config path and sections**: Config file path is resolved only via `get_config_path()` (used by doctor and all section load/save). Section load/save (`image_cache`, `ignore`, `upload`) use internal `_load_section()` / `_save_section()` with per-section parse and serialize functions; public API (e.g. `load_image_cache_config`) remains unchanged.
- **Project resolution in CLI**: Commands that need a project (fetch, fetch-task, ignore, upload) use `resolve_project_from_args(project_arg, client)` from `_helpers` when the user passes `--project`; when not passed, they use `select_project_tui(client)` (fetch/upload) or ignore-specific TUI (ignore). No command imports another command’s private helpers for project selection.
- `_RECTANGLE = "rectangle"` in `cveta2/_client/context.py` — only rectangle/box shapes are extracted; other shape types are skipped.
- **Tracks are intentionally not processed.** Track-based annotations (interpolated/linked bboxes in `RawAnnotations.tracks`) are fetched from CVAT but skipped during extraction. cveta2 targets per-frame bbox exports, not temporal tracking data. A warning is logged when tracks are present. The `RawTrack`/`RawTrackedShape` DTOs are retained because the fixture infrastructure and export scripts need the complete CVAT data model.
- `_collect_shapes` processes shapes regardless of frame deletion status — shapes on deleted frames are still extracted as `BBoxAnnotation`. Deletion filtering is handled later by `partition_annotations_df` via the `deleted_images` list.
- `fetch_annotations()` wrapper returns a `pd.DataFrame` (not `ProjectAnnotations`); for structured output use `CvatClient.fetch_annotations()`.
- `ProjectAnnotations.to_csv_rows()` iterates the single `annotations` list (which contains both `BBoxAnnotation` and `ImageWithoutAnnotations` via `AnnotationRecord` union) and calls `to_csv_row()` on each. The legacy `_project_annotations_to_csv_rows()` wrapper in `client.py` delegates to this method.
- `ensure_credentials()` on `CvatConfig` returns a new copy with prompted values — it never mutates in place.
- If `token` is present, `ensure_credentials()` does not prompt for username/password.
- `main.py` kept at project root for backwards compatibility with `python main.py fetch ...` invocations.
- `_write_json_output()` in CLI uses `logger._core.min_level` (private loguru API) to check whether debug logging is enabled before printing JSON to stdout.
- **Image download is orthogonal to annotations.** `CvatClient.download_images()` uses `_raw_sdk` (stored directly in `__enter__`, not extracted from `_persistent_api`) because cloud storage detection and S3 download are a separate concern from annotation fetching. The method requires an active context manager (`with CvatClient(cfg) as c:`). `parse_cloud_storage()` in `image_downloader.py` uses `getattr` on the CVAT SDK cloud storage object (intentional exception to style rule — SDK objects are opaque). The `ImageDownloader` pipeline: `_collect_unique_images()` (dict[str,int]) -> `_filter_cached()` -> `_download_all()` (resolves cloud storages, creates S3 clients, downloads).
- **S3 key construction** in `_build_s3_key()`: if `frame_name` already starts with `prefix`, it's used as-is; otherwise `prefix/frame_name`; if prefix is empty, just `frame_name`. This handles different CVAT versions where frame names may or may not include the cloud storage prefix.
- **Cloud storage auto-detection**: `ImageDownloader._detect_cloud_storage()` reads `source_storage` from the CVAT task object to get `cloud_storage_id`, then retrieves full cloud storage details via `cloudstorages_api.retrieve()`. Results are cached per `cloud_storage_id` within a download session. If a task has no `source_storage`, its images are counted as `failed` in `DownloadStats`.
- **S3 credentials** for image download rely on the standard boto3 credential chain (`~/.aws/credentials`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars, IAM roles, etc.). No S3 credentials are stored in the cveta2 config.
- **S3 sync is one-directional.** `S3Syncer` and the `s3-sync` CLI command only download from S3 to local storage. They never upload to S3 and never delete S3 objects. Local files not present in S3 are preserved (not deleted). `_list_s3_objects()` uses `list_objects_v2` with pagination support for large buckets.
- **`s3-sync` cloud storage detection** reuses `ImageDownloader._detect_cloud_storage()` via `CvatClient.detect_project_cloud_storage()`. It probes project tasks in order and returns the first `CloudStorageInfo` found. If no task has a `source_storage`, the project is skipped with a warning.
- **`upload` reuses S3 infrastructure from `image_downloader.py`**: `CloudStorageInfo`, `_build_s3_key`, `_list_s3_objects`, `_s3_retry` are imported and reused by `image_uploader.py` for S3 upload operations. Cloud storage detection reuses `CvatClient.detect_project_cloud_storage()`.
- **`upload` creates tasks via CVAT low-level API**: Uses `tasks_api.create()` + `tasks_api.create_data()` with `DataRequest(server_files=..., cloud_storage_id=..., use_cache=True, sorting_method="natural")` to create a task backed by cloud storage. The `segment_size` parameter on `TaskWriteRequest` controls how CVAT auto-splits the task into jobs. After `create_data`, the method **polls CVAT** (up to `data_processing_timeout` seconds, default 60) waiting for `task.size > 0` — without this wait, annotation uploads arrive before frames are indexed and are silently discarded. Annotation frame indices are read from CVAT `data_meta.frames` (not assumed from the input list order) to ensure correct mapping.
- **`merge` split propagation** runs after `pd.concat` in `_merge_datasets()`. It builds a `{image_name: split}` lookup from old rows with non-null `split`, then fills null splits in the merged result via `DataFrame.map()`. Conflict detection compares common images where both datasets have non-null split values. The winner's split is never overwritten — only null slots are filled. If the old dataset has no `split` column or all split values are NaN, a warning is logged and propagation is skipped.
- **`upload` sends all filtered image names to CVAT** regardless of whether they were found locally. Images already on S3 (but not found locally) will still be included in the task. Missing images that are neither local nor on S3 produce a warning but do not block task creation.

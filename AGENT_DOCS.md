# Agent Documentation

Short descriptions of project internals and implicit design decisions.

## Package structure

```
cveta2/
  __init__.py   - public API re-exports: CvatClient, fetch_annotations, BBoxAnnotation, DeletedImage, ImageWithoutAnnotations, ProjectAnnotations, partition_annotations_df, PartitionResult
  models.py     - Pydantic models: BBoxAnnotation, DeletedImage, ImageWithoutAnnotations, ProjectAnnotations
  dataset_partition.py - partition_annotations_df(): pandas-based partitioning of annotation DataFrame into dataset/obsolete/in_progress; PartitionResult dataclass
  config.py     - CvatConfig pydantic model; loads/merges env > config file; get_projects_cache_path(); is_interactive_disabled() / require_interactive() guards
  projects_cache.py - YAML cache of project id/name list (load_projects_cache, save_projects_cache); path next to config (projects.yaml)
  client.py     - CvatClient class (list_projects, resolve_project_id, fetch_annotations) + fetch_annotations() DataFrame wrapper + _project_annotations_to_csv_rows(); all paths go through CvatApiPort
  _client/      - internal implementation details split from client.py
    dtos.py     - frozen dataclass DTOs for CVAT API responses (RawFrame, RawShape, RawTrack, RawTask, RawLabel, etc.)
    ports.py    - CvatApiPort Protocol defining the API boundary; the single seam for mocking
    sdk_adapter.py - SdkCvatApiAdapter: CvatApiPort implementation wrapping an open cvat_sdk client; thin stateless converter (SDK objects in, DTOs out); only _extract_updated_date and _extract_creator_username use getattr for optional/legacy fields
    context.py  - _TaskContext + extraction constants; frames typed as dict[int, RawFrame]; get_frame() and get_label_name() for extractors; from_raw(task, data_meta, label_names, attr_names) classmethod builds context from DTOs
    mapping.py  - helper functions for label/attribute mapping; takes typed DTOs (RawLabel, RawAttribute)
    extractors.py - shape/track conversion into BBoxAnnotation models; takes typed DTOs (RawShape, RawTrack)
    (context.py, mapping.py, extractors.py entries above — no duplicates)

  cli.py        - argparse CLI entry point; CliApp class with setup/fetch handlers and CSV/TXT exports
  __main__.py   - enables `python -m cveta2`
main.py         - thin backwards-compat wrapper delegating to cveta2.cli.main()
```

## Config resolution

Priority: env vars override config file. No CVAT settings/credentials on CLI. Env: `CVAT_HOST`, `CVAT_ORGANIZATION`, `CVAT_TOKEN`, `CVAT_USERNAME`, `CVAT_PASSWORD`. Config file path: `CVETA2_CONFIG` or default `~/.config/cveta2/config.yaml`. If host is missing, CLI suggests running `cveta2 setup` or setting env. Config file uses YAML with `cvat` mapping to `CvatConfig` fields. Organization is applied via `client.organization_slug` after client creation.

## Non-interactive mode

Set `CVETA2_NO_INTERACTIVE=true` (case-insensitive) to disable all interactive prompts. When set, any operation that would require user input raises `RuntimeError` with a hint about which CLI flag or env var to use instead. The variable can be unset or empty — defaults to interactive mode enabled. Guarded locations: `cveta2 setup` (entire command), TUI project selection in `fetch` (use `--project`), credential prompts in `ensure_credentials()` (use `CVAT_TOKEN` / `CVAT_USERNAME` + `CVAT_PASSWORD`). The output-dir overwrite prompt silently overwrites in non-interactive mode instead of raising. Helper functions: `is_interactive_disabled()` and `require_interactive(hint)` in `config.py`.

## CLI commands

- `setup` — interactive wizard that prompts for host and auth (token or username/password), saves to `~/.config/cveta2/config.yaml` via `CvatConfig.save_to_file()`. Prefills defaults from existing config if present. Optional `--config` to override config path.
- `fetch` — fetches bbox annotations and deleted images from a CVAT project, splits them into three CSVs. Arguments:
  - `--project` / `-p` — project ID (number) or project name; if omitted, TUI shows cached project list with arrow-key selection and search filter; "↻ Обновить список" rescans CVAT and refreshes cache.
  - `--output-dir` / `-o` (required) — directory for output files: `dataset.csv`, `obsolete.csv`, `in_progress.csv`, `deleted.txt`.
  - `--raw` — additionally save unprocessed full DataFrame as `raw.csv` in the output dir.
  - `--completed-only` — process only tasks with status "completed" (in_progress.csv will be empty).

## Logging levels

- **INFO** — file save confirmations (`Annotations CSV saved`, `Deleted images list saved`, `Config saved`), interactive prompts, cache status messages.
- **DEBUG** — API result summaries (project info, task counts, annotation/deleted/without-annotations counts, processing task progress), full JSON to stdout, API structure dumps (project, tasks, data_meta, annotations).
- **TRACE** — raw API object dumps (individual shapes, frames, deleted_frames, labels, attributes).

## Data model notes

- `BBoxAnnotation` includes task metadata (`task_id`, `task_name`, `task_status`, `task_updated_date`), source metadata (`created_by_username`, `source`, `annotation_id`), and frame metadata (`frame_id`, `subset`, image size).
- `BBoxAnnotation.to_csv_row()` serializes `attributes` as a JSON string (`ensure_ascii=False`) so non-ASCII attribute values remain readable in CSV.
- `ImageWithoutAnnotations` — frames with no bbox annotations; included in CSV via `to_csv_row()` with None for bbox/annotation fields.
- `ProjectAnnotations` contains `annotations`, `deleted_images`, and `images_without_annotations`.
- `DeletedImage` — record of a deleted frame: `task_id`, `task_name`, `task_status`, `task_updated_date`, `frame_id`, `image_name`.

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
- **FakeCvatApi**: `tests/fixtures/fake_cvat_api.py` — implements `CvatApiPort` protocol, backed by `LoadedFixtures` tuple (canonical definition in `fake_cvat_project.py`, imported everywhere else). Injected into `CvatClient(cfg, api=FakeCvatApi(fixtures))` for integration tests without SDK.
- **Tests**: `tests/test_cvat_fixtures.py` — loads coco8-dev fixtures, runs name-based consistency checks per task (e.g. task "all-removed" → every frame in deleted_frames; "normal" → at least one frame not deleted). No CvatClient; assertions on DTOs only. Task name → assertion registry: normal, all-empty, all-removed, zero-frame-empty-last-removed, all-bboxes-moved, all-except-first-empty, frames-1-2-removed.
- **Fake projects**: `tests/fixtures/fake_cvat_project.py` — build fake projects from base fixtures (e.g. coco8-dev) for tests. `FakeProjectConfig` (pydantic): `task_indices` (which base tasks, in order; can repeat), or `count` + random sampling; `task_id_order` ("asc" | "random"); `task_names` ("keep" | "random" | "enumerated" | list); `task_statuses` ("keep" | "random" | list); `seed` for reproducibility. `build_fake_project(base_fixtures, config)` returns the same `(RawProject, list[RawTask], list[RawLabel], task_id -> (RawDataMeta, RawAnnotations))` structure. `task_indices_by_names(base_tasks, ["normal", "all-removed"])` resolves names to indices. Tests in `tests/test_fake_cvat_project.py`.
- **Shared fixtures**: `tests/conftest.py` — session-scoped `coco8_fixtures`, `coco8_label_maps`, `coco8_tasks_by_name` for use across all test modules.
- **Pipeline tests**: `test_mapping.py` (label/attribute mapping), `test_extractors.py` (_collect_shapes unit tests), `test_partition.py` (partition_annotations_df), `test_pipeline_integration.py` (full pipeline via FakeCvatApi + CvatClient).

## Dev tools (scripts/)

- `scripts/upload_dataset_to_cvat.py` — creates a CVAT project and several tasks from a dataset YAML (e.g. coco8). Reads `path`, `train`, `val`, `names`; creates one project with labels from `names` and N tasks each with the same images (train+val). Uses `cveta2.config.CvatConfig` and cvat_sdk directly (no CvatApiPort). Run from repo root: `uv run python scripts/upload_dataset_to_cvat.py [--yaml path] [--project name] [--tasks N]`.
- `scripts/export_cvat_fixtures.py` — exports a CVAT project to JSON fixtures for tests. Uses only cvat_sdk; credentials via env. See "Test fixtures (CVAT)" above and `scripts/README.md`.

## Implicit decisions

- `_RECTANGLE = "rectangle"` in `cveta2/_client/context.py` — only rectangle/box shapes are extracted; other shape types are skipped.
- `_collect_shapes` processes shapes regardless of frame deletion status — shapes on deleted frames are still extracted as `BBoxAnnotation`. Deletion filtering is handled later by `partition_annotations_df` via the `deleted_images` list.
- `fetch_annotations()` wrapper returns a `pd.DataFrame` (not `ProjectAnnotations`); for structured output use `CvatClient.fetch_annotations()`.
- `_project_annotations_to_csv_rows()` merges `BBoxAnnotation` and `ImageWithoutAnnotations` rows into a single flat list for CSV.
- `ensure_credentials()` on `CvatConfig` returns a new copy with prompted values — it never mutates in place.
- If `token` is present, `ensure_credentials()` does not prompt for username/password.
- `main.py` kept at project root for backwards compatibility with `python main.py fetch ...` invocations.
- `_write_json_output()` in CLI uses `logger._core.min_level` (private loguru API) to check whether debug logging is enabled before printing JSON to stdout.

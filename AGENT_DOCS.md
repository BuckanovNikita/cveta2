# Agent Documentation

Short descriptions of project internals and implicit design decisions.

## Package structure

```
cveta2/
  __init__.py   - public API re-exports: CvatClient, fetch_annotations, BBoxAnnotation, DeletedImage, ImageWithoutAnnotations, ProjectAnnotations
  models.py     - Pydantic models: BBoxAnnotation, DeletedImage, ImageWithoutAnnotations, ProjectAnnotations
  config.py     - CvatConfig pydantic model; loads/merges env > config file; get_projects_cache_path()
  projects_cache.py - YAML cache of project id/name list (load_projects_cache, save_projects_cache); path next to config (projects.yaml)
  client.py     - CvatClient class (list_projects, resolve_project_id, fetch_annotations) + fetch_annotations() DataFrame wrapper + _project_annotations_to_csv_rows()
  _client/      - internal implementation details split from client.py
    context.py  - _TaskContext + extraction constants
    mapping.py  - helper functions for label/attribute mapping
    extractors.py - shape/track conversion into BBoxAnnotation models
  cli.py        - argparse CLI entry point; CliApp class with setup/fetch handlers and CSV/TXT exports
  __main__.py   - enables `python -m cveta2`
main.py         - thin backwards-compat wrapper delegating to cveta2.cli.main()
```

## Config resolution

Priority: env vars override config file. No CVAT settings/credentials on CLI. Env: `CVAT_HOST`, `CVAT_ORGANIZATION`, `CVAT_TOKEN`, `CVAT_USERNAME`, `CVAT_PASSWORD`. Config file path: `CVETA2_CONFIG` or default `~/.config/cveta2/config.yaml`. If host is missing, CLI suggests running `cveta2 setup` or setting env. Config file uses YAML with `cvat` mapping to `CvatConfig` fields. Organization is applied via `client.organization_slug` after client creation.

## CLI commands

- `setup` — interactive wizard that prompts for host and auth (token or username/password), saves to `~/.config/cveta2/config.yaml` via `CvatConfig.save_to_file()`. Prefills defaults from existing config if present. Optional `--config` to override config path.
- `fetch` — fetches bbox annotations and deleted images from a CVAT project. Arguments:
  - `--project` / `-p` — project ID (number) or project name; if omitted, TUI shows cached project list with arrow-key selection and search filter; "↻ Обновить список" rescans CVAT and refreshes cache.
  - `--annotations-csv` — save annotations + images-without-annotations as CSV.
  - `--deleted-txt` — save deleted image names (one per line).
  - `--completed-only` — process only tasks with status "completed".
  - No `-o`/`--output` flag. Full JSON is written to stdout only when `LOGURU_LEVEL=DEBUG` (hidden at INFO to keep output clean).

## Logging levels

- **INFO** — file save confirmations (`Annotations CSV saved`, `Deleted images list saved`, `Config saved`), interactive prompts, cache status messages.
- **DEBUG** — API result summaries (project info, task counts, annotation/deleted/without-annotations counts, processing task progress), full JSON to stdout, API structure dumps (project, tasks, data_meta, annotations).
- **TRACE** — raw API object dumps (individual shapes, tracks, tracked shapes, frames, deleted_frames, labels, attributes).

## Data model notes

- `BBoxAnnotation` includes task metadata (`task_id`, `task_name`, `task_status`, `task_updated_date`), source metadata (`created_by_username`, `source`, `annotation_id`), and frame metadata (`frame_id`, `subset`, image size).
- `BBoxAnnotation.to_csv_row()` serializes `attributes` as a JSON string (`ensure_ascii=False`) so non-ASCII attribute values remain readable in CSV.
- `ImageWithoutAnnotations` — frames with no bbox annotations; included in CSV via `to_csv_row()` with None for bbox/annotation fields.
- `ProjectAnnotations` contains `annotations`, `deleted_images`, and `images_without_annotations`.
- `DeletedImage` — minimal record: `task_id`, `task_name`, `frame_id`, `image_name`.

## Implicit decisions

- `_RECTANGLE = "rectangle"` in `cveta2/_client/context.py` — only rectangle/box shapes are extracted; other shape types are skipped.
- Track extraction ignores shapes with `outside=True`; only visible track boxes are converted into `BBoxAnnotation`.
- `fetch_annotations()` wrapper returns a `pd.DataFrame` (not `ProjectAnnotations`); for structured output use `CvatClient.fetch_annotations()`.
- `_project_annotations_to_csv_rows()` merges `BBoxAnnotation` and `ImageWithoutAnnotations` rows into a single flat list for CSV.
- `ensure_credentials()` on `CvatConfig` returns a new copy with prompted values — it never mutates in place.
- If `token` is present, `ensure_credentials()` does not prompt for username/password.
- `main.py` kept at project root for backwards compatibility with `python main.py fetch ...` invocations.
- `_write_json_output()` in CLI uses `logger._core.min_level` (private loguru API) to check whether debug logging is enabled before printing JSON to stdout.

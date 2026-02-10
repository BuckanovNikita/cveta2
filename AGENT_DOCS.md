# Agent Documentation

Short descriptions of project internals and implicit design decisions.

## Package structure

```
cveta2/
  __init__.py   - public API re-exports: fetch_annotations, BBoxAnnotation, DeletedImage, ProjectAnnotations
  models.py     - Pydantic models for annotation data (BBoxAnnotation, DeletedImage, ProjectAnnotations)
  config.py     - CvatConfig pydantic model; loads and merges settings from CLI > env > config file
  client.py     - public CVAT client facade: CvatClient class + fetch_annotations() wrapper
  _client/      - internal implementation details split from client.py
    context.py  - _TaskContext + extraction constants
    mapping.py  - helper functions for label/attribute/user mapping
    extractors.py - shape/track conversion into BBoxAnnotation models
  cli.py        - argparse CLI entry point; CliApp class with setup/fetch handlers and optional CSV/TXT exports
  __main__.py   - enables `python -m cveta2`
main.py         - thin backwards-compat wrapper delegating to cveta2.cli.main()
```

## Config resolution

Priority: env vars override config file. No CVAT settings/credentials on CLI. Env: `CVAT_HOST`, `CVAT_ORGANIZATION`, `CVAT_TOKEN`, `CVAT_USERNAME`, `CVAT_PASSWORD`. Config file path: `CVETA2_CONFIG` or default `~/.config/cveta2/config.yaml`. If host is missing, CLI suggests running `cveta2 setup` or setting env. Config file uses YAML with `cvat` mapping to `CvatConfig` fields. Organization is applied via `client.organization_slug` after client creation.

## CLI commands

- `setup` — interactive wizard that prompts for host and auth (token or username/password), saves to `~/.config/cveta2/config.yaml` via `CvatConfig.save_to_file()`. Prefills defaults from existing config if present.
- `fetch` — fetches bbox annotations and deleted images from a CVAT project. Optional `--annotations-csv` and `--deleted-txt` write CSV (all bbox rows) and one-per-line deleted image names respectively. `--completed-only` limits processing to tasks with status `"completed"`. JSON output is written to stdout unless `--output` is set.

## Data model notes

- `BBoxAnnotation` includes task metadata (`task_id`, `task_name`, `task_status`, `task_updated_date`), source metadata (`created_by_username`, `source`, `annotation_id`), and frame metadata (`frame_id`, `subset`, image size).
- `BBoxAnnotation.to_csv_row()` serializes `attributes` as a JSON string (`ensure_ascii=False`) so non-ASCII attribute values remain readable in CSV.
- `ProjectAnnotations` contains `annotations`, `deleted_images`, and `images_without_annotations` (frames that have no bbox; included in CSV with None for bbox/annotation fields).

## Implicit decisions

- `_RECTANGLE = "rectangle"` in `cveta2/_client/context.py` — only rectangle/box shapes are extracted; other shape types are skipped.
- Track extraction ignores shapes with `outside=True`; only visible track boxes are converted into `BBoxAnnotation`.
- `fetch_annotations()` is a thin wrapper over `CvatClient.fetch_annotations()` and returns `ProjectAnnotations`.
- `ensure_credentials()` on `CvatConfig` returns a new copy with prompted values — it never mutates in place.
- If `token` is present, `ensure_credentials()` does not prompt for username/password.
- `main.py` kept at project root for backwards compatibility with `python main.py fetch ...` invocations.

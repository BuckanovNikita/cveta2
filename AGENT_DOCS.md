# Agent Documentation

Short descriptions of project internals and implicit design decisions.

## Package structure

```
cveta2/
  __init__.py   - public API re-exports: fetch_annotations, BBoxAnnotation, DeletedImage, ProjectAnnotations
  models.py     - Pydantic models for annotation data (BBoxAnnotation, DeletedImage, ProjectAnnotations)
  config.py     - CvatConfig pydantic model; loads and merges settings from CLI > env > config file
  client.py     - CVAT SDK interaction: CvatClient class + fetch_annotations() wrapper
  cli.py        - argparse CLI entry point; CliApp class with setup/fetch handlers
  __main__.py   - enables `python -m cveta2`
main.py         - thin backwards-compat wrapper delegating to cveta2.cli.main()
```

## Config resolution

Priority chain (highest wins): CLI args > env vars (`CVAT_HOST`, `CVAT_TOKEN`, etc.) > `~/.config/cveta2/config.yaml` > interactive prompt.

Config file uses YAML format, parsed with `pyyaml`. The `cvat` mapping maps directly to `CvatConfig` fields.

## CLI commands

- `setup` — interactive wizard that prompts for host and auth (token or username/password), saves to `~/.config/cveta2/config.yaml` via `CvatConfig.save_to_file()`. Prefills defaults from existing config if present.
- `fetch` — fetches bbox annotations and deleted images from a CVAT project. Optional `--annotations-csv` and `--deleted-txt` write CSV (all bbox rows) and one-per-line deleted image names respectively. `--completed-only` limits processing to tasks with status `"completed"`.

## Implicit decisions

- `_RECTANGLE = "rectangle"` in `client.py` — only rectangle/box shapes are extracted; other shape types are silently skipped.
- `fetch_annotations()` is a thin wrapper over `CvatClient.fetch_annotations()` and accepts `CvatConfig` to decouple credential resolution from CVAT API calls.
- `ensure_credentials()` on `CvatConfig` returns a new copy with prompted values — it never mutates in place.
- `main.py` kept at project root for backwards compatibility with `python main.py fetch ...` invocations.

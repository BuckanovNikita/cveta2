# Agent Documentation

Short descriptions of project internals and implicit design decisions.

## Package structure

```
cveta2/
  __init__.py   - public API re-exports: fetch_annotations, BBoxAnnotation, DeletedImage, ProjectAnnotations
  models.py     - Pydantic models for annotation data (BBoxAnnotation, DeletedImage, ProjectAnnotations)
  config.py     - CvatConfig pydantic model; loads and merges settings from CLI > env > config file
  client.py     - CVAT SDK interaction: fetch_annotations() and internal shape extraction helpers
  cli.py        - argparse CLI entry point; wires config loading into client calls
  __main__.py   - enables `python -m cveta2`
main.py         - thin backwards-compat wrapper delegating to cveta2.cli.main()
```

## Config resolution

Priority chain (highest wins): CLI args > env vars (`CVAT_HOST`, `CVAT_TOKEN`, etc.) > `~/.config/cveta2/config.toml` > interactive prompt.

Config file uses TOML format, parsed with stdlib `tomllib` (Python 3.11+). The `[cvat]` section maps directly to `CvatConfig` fields.

## Implicit decisions

- `_RECTANGLE = "rectangle"` in `client.py` — only rectangle/box shapes are extracted; other shape types are silently skipped.
- `fetch_annotations()` accepts a `CvatConfig` object (not raw host/token args) to decouple credential resolution from CVAT API calls.
- `ensure_credentials()` on `CvatConfig` returns a new copy with prompted values — it never mutates in place.
- `main.py` kept at project root for backwards compatibility with `python main.py fetch ...` invocations.

# Validation guide

Install the existing development environment with `uv sync --dev` from the
repository root. Tests isolate user configuration and caches.

```bash
uv run pytest tests/test_extractors.py tests/test_sdk_adapter_conversion.py tests/test_polygon_fetch.py tests/test_polygon_cache.py tests/test_task_cache.py
uv run pytest tests/test_client_ops_fetch.py tests/test_fetch_service.py tests/test_fetch_task.py tests/test_convert_coco.py tests/test_convert_common.py tests/test_convert_yolo.py tests/test_docs.py
uv run ruff check .
uv run mypy .
uv run lint-imports
```

The triangle yields `(12.0, 10.25, 90.75, 80.0)` and an approximation warning;
polygon-only frames yield box rows through either fetch path. Malformed polygons
warn and contribute to a task skip summary. Deleted-frame precedence is retained.
Version-4 local/S3 entries miss; fresh polygon boxes survive subsequent reads.

Run the configured commit/push gates described in
[engineering guidance](../../.specify/memory/engineering.md#commits-hooks-and-releases).
Record results in dated feature evidence; live shared resources require the
repository integration skill and exact-tag cleanup.

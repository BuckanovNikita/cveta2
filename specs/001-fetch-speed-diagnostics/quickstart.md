# Validation quickstart

Use the checkout's uv environment and existing isolated pytest configuration.

```bash
uv run pytest tests/test_image_downloader.py tests/test_client_ops_fetch.py tests/test_fetch_skip_validation.py tests/test_retry_policy.py
uv run lint-imports
uv run python scripts/check_architecture.py
uv run pytest tests/test_architecture.py tests/test_docs.py
```

New focused tests add counted GET/list/filesystem/output effects and controlled
HTTP diagnostics. Run the full gate and owned serial integration using the project
integration skill before acceptance; no user credentials belong in this guide.
Compare before/after benchmark workloads with unchanged workers, recording raw
measurements and scope in evidence. See [plan](plan.md) for complete acceptance.

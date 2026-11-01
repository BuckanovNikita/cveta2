# Validation

From the repository with its uv development environment:

```bash
uv run pytest tests/test_review_interfaces.py tests/test_config_sections.py tests/test_config_helpers.py tests/test_retry_policy.py tests/test_cvat_diagnostics.py
uv run lint-imports
uv run python scripts/check_architecture.py
uv run pytest tests/test_architecture.py
```

Regressions reproduce the original failure before the fix and pass afterward; existing boundary cases remain green. Final mutation/live evidence belongs in the dated verification record.

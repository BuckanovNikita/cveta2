# Validation

From the repository with its uv development environment:

```bash
uv run pytest tests/test_partition.py tests/test_whats_new.py
uv run lint-imports
uv run python scripts/check_architecture.py
uv run pytest tests/test_architecture.py
```

Regressions reproduce the original failure before the fix and pass afterward; existing boundary cases remain green. Final mutation/live evidence belongs in the dated verification record.

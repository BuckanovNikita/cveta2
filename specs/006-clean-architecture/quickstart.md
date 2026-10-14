# Verification scenarios

Run from the feature worktree with its locked environment:

```bash
uv sync --dev --locked
uv run lint-imports
uv run pytest tests/test_architecture.py
uv run pytest --cov --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run vulture
./scripts/mutation_test.sh --profile fast
./scripts/mutation_test.sh --profile full
uv build
```

Check public signatures, model identities and CLI discovery; run workflows through recording ports. Exercise disabled-cache invalidation, strict promotion ordering, resume ambiguity, partial transfers, deletion precedence and conversion materialization. Inject architecture violations in isolated fixtures and verify rejection. Follow the installed running-integration-tests skill for serial full live checks and exact-tag cleanup. Record evidence, then finish fresh review, convergence and architecture acceptance before release.

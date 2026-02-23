# Style preferences 
1. always use loguru for logging not print
1. Use pydantic schemas for all configs
1. prefer f-strings to loguru structured output
1. avoid using getattr, hasattr, direct access to the __dict__ 

# Documentation guidelines 
1. always write to README.md in russian
1. Write README.md as user friendly intro rich with examples, not as wall of internals
1. Write CIONTRIBUTING.md in russian
1. Try avoid using strings instead ofg types if it's not strictly neccessary..
1. Update README.md and AGENT_DOCS when finishing task or make breaking api changes.

# Linters & quality tools

All tools run via `uv run` and are enforced in pre-commit (`pre-commit run --all-files`).

## Running everything at once

```bash
pre-commit run --all-files   # full pipeline in correct order
```

## Individual tools

### 1. ruff format (formatter)
```bash
uv run ruff format .         # format everything
uv run ruff format --check . # dry-run, exits non-zero if unformatted
```
Config: `line-length = 88`, `target-version = "py310"`, `docstring-code-format = true`.
The `scripts/` directory is formatted but NOT linted.

### 2. ruff check (linter)
```bash
uv run ruff check .          # lint
uv run ruff check --fix .    # auto-fix safe violations
```
Config selects `ALL` rules with specific ignores (see `[tool.ruff.lint]` in `pyproject.toml`).
Key per-file overrides: `tests/**` silences `S101` (assert), `D102`/`D103` (missing docstrings), etc.
`scripts/**` is fully excluded from linting.

### 3. mypy (type checker)
```bash
uv run mypy .
```
Runs in `strict = true` mode. The `scripts/` and `vendor/` dirs are excluded.
`cvat_sdk.*` has `ignore_missing_imports = true` because it ships incomplete stubs.
Type stubs for third-party libs (`boto3-stubs`, `pandas-stubs`, `types-tqdm`, `types-pyyaml`) are in the dev dependency group.

### 4. import-linter (architecture contracts)
```bash
uv run lint-imports
```
Enforces three contracts defined in `pyproject.toml`:
- **Layers**: `cli → commands → client → _client` (no upward imports).
- **Foundation isolation**: `models` and `exceptions` must not import from `client`, `commands`, `cli`, or `_client`.
- **Config isolation**: `config` must not import from any higher-level or domain modules.

When adding new modules decide which layer they belong to and update the contracts if needed.

### 5. vulture (dead code)
```bash
uv run vulture
```
Scans `cveta2/` and `main.py` with `min_confidence = 80`. If vulture flags something that is actually used (e.g. a public API), add a whitelist entry or raise confidence.

### 6. pytest (tests)
```bash
uv run pytest              # uses defaults from pyproject.toml (-v --tb=short -n auto)
uv run pytest -x           # stop on first failure
uv run pytest -k "test_labels"  # run by name
```
`-n auto` enables parallel execution via `pytest-xdist`. Integration tests are gated by the `CVAT_INTEGRATION_HOST` env var.

## Pre-commit order and tips
The hooks run in this order: format → lint → import-linter → mypy → vulture → pytest → count-lines → build → lock.
Always run `ruff format` before `ruff check` — the formatter can introduce/fix lint issues.
If mypy or ruff report new errors after your change, fix them before committing.

# Other instructions 
Refers to AGENT_DOCS.md for short project documentation. Add short descriptions about implicit or hard code solutions to it if needed. 


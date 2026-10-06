# Verify and maintain the migrated documentation

From the repository root:

```bash
export SPECIFY_FEATURE_DIRECTORY=specs/001-project-documentation
.specify/scripts/bash/check-prerequisites.sh --paths-only --json
.specify/scripts/bash/check-prerequisites.sh --json --require-spec --require-tasks --include-tasks
uv run pytest tests/test_docs.py
uv run ruff check tests/test_docs.py cveta2/api.py
uv run ruff format --check tests/test_docs.py cveta2/api.py
uv run mypy tests/test_docs.py cveta2/api.py
uvx --from git+https://github.com/github/spec-kit.git@v1.0.13 specify integration status --json
```

Build the source distribution into a task-owned temporary directory with
`uv build --sdist --out-dir <temporary-directory>`. Inspect the archive for
`specs/001-project-documentation/contracts/dataset-format.md`, compare its
content with the living contract, and remove the temporary directory.

Follow AGENTS.md to memory before planning; update shared architecture and
contract sources when a later behavior specification changes them. Keep
historical evidence dated and do not reopen accepted findings without a
requested contract change. Set the feature override explicitly when resuming;
unset it before creating an unrelated new feature.

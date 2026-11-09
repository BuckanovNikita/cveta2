# Validation guide

Sync the locked development environment, inspect load, choose a bounded
`CVETA2_TEST_WORKERS`, and install hooks with `bash scripts/install-hooks.sh`.
Run `uv run --locked task --exit-code fix`, inspect changes and stage exact paths.
Use `uv run --locked task --exit-code verify` for working-copy development checks.

Record initial and unchanged unit runs, Python changes, failed tests, interrupted
runs, and configuration/static-asset/file-membership changes in disposable repos.
Exercise the staging shim before prek on partially staged and nonignored untracked
inputs. Validate legacy and current worktrees and restore the saved installation.

On a clean committed tip, run `uv run --locked task --exit-code acceptance`.
AVAILABLE/0 permits live tests; UNAVAILABLE/3 defers; ERROR/1 requires diagnosis.
Report passed, failed, deferred and incomplete-cleanup outcomes separately. Deferred
acceptance stays unchecked in tasks.md. Do not create a tooling-only test suite.

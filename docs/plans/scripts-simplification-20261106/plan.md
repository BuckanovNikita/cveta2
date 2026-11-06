# scripts/ simplification: maintenance plan

Date: 2026-11-06. Source analysis: [analysis.md](analysis.md). Decision: the owner
asked for all three tiers, committed and pushed to `project-cleunap`.

## Workflow selection

This is development-tooling maintenance. The `cveta2` package, its CLI, its public
API and the dataset contract do not change, so per
[engineering guidance](../../../.specify/memory/engineering.md#spec-kit-development-workflow)
it uses the lightweight path: this plan, [tasks.md](tasks.md), an adjacent
[architecture.json](architecture.json) and dated verification evidence. No Spec Kit
feature is created; `.specify/feature.json` (spec 005) is left untouched.

## Accepted behaviour losses

- **Tier 1, commit-msg.** The stock `compilerla/conventional-pre-commit` v4.5.0 hook
  replaces `check_commit_msg.py`. Merge and autosquash subjects stay exempt (its
  non-strict default; source checked). Lost: the rule that a `!` subject needs a
  `BREAKING CHANGE:` footer. Also, git's default `Revert "..."` subject is now
  rejected (write `revert`-style subjects as a conventional type instead), and type
  matching becomes case-insensitive.
- Nothing else is lost: every other script is moved, merged or ported with parity
  tests.

## Changes

### Tier 1
1. `check_commit_msg.py` → remote hook `conventional-pre-commit` v4.5.0 with the same
   10 types, stage `commit-msg`.
2. `check_version_drift.py` → inline pre-push `bash -c` entry comparing
   `v$(uv version --short)` with `git describe --tags --abbrev=0`; no tag means pass.
3. `scripts/check_architecture.py` → `tests/architecture_effects.py` (helper, no
   CLI). `tests/test_architecture.py` already asserts `check_tree(PACKAGE) == []`
   on the real package, and the pytest hook runs every commit, so the
   `architecture-effects` hook is dropped.
4. Delete `upload_dataset_to_cvat.py` and `export_cvat_fixtures.py` and their docs.
5. `scripts/clone_project_to_s3.py` → `tests/integration/clone_project_to_s3.py`,
   reusing `cveta2.adapters.cvat.storage.parse_cloud_storage` and
   `cveta2.domain.storage.CloudStorageInfo` instead of its duplicates.

### Tier 2
6. `mutation_test.sh` + `mutation_config.py` + `mutation_gate.py` → one
   `scripts/mutation.py`. Preserved: profile resolution before any workspace
   change, an empty profile meaning a bare `mutmut run`, `sync-scope` before the
   run, `PYTEST_DEBUG_TEMPROOT` under `mutants/`, CR-spinner stripping when stdout
   is not a TTY, glob narrowing of survivors and allowlist, stale-entry failure,
   argument pass-through, and the score summary.

### Tier 3
7. The five `integration_*.sh` scripts → one stdlib-only Python CLI
   `tests/integration/lifecycle.py`, run as
   `uv run python -m tests.integration.lifecycle {env,up,test,stop,gate}`.
   It is a CLI rather than pytest fixtures because `tests.env_isolation` replaces
   HOME at pytest start-up, which would hide the installed k8s-infra skill, and the
   gate's preflight and keep/stop policy must run outside pytest. `env` prints shell
   exports, replacing `source scripts/integration_env.sh` for manual use. A SIGTERM
   handler turns termination into a normal exit so teardown still runs. The hook id
   `integration-tests` and `verbose: true` stay, so `SKIP=integration-tests` keeps
   working.
8. `tests/test_integration_env.py` is ported to `tests/test_integration_lifecycle.py`
   with every assertion kept, as the parity specification.

### Documentation
`scripts/README.md` (Russian), `CONTRIBUTING.md`, `.specify/memory/engineering.md`,
`.specify/memory/architecture.md`, the `commit`, `mutation-testing` and
`running-integration-tests` skills, `tests/integration/.env.example`, integration
docstrings and messages, and the `pyproject.toml` comments that name removed paths.
Historical `specs/*` and `docs/plans/*` records are not rewritten. The portable
corp-skills `cveta2` skill documents tool usage only; check it for references to
the removed paths.

## Architecture

See [architecture.json](architecture.json). No runtime package module changes
except a docstring in `cveta2/adapters/cvat/storage.py`. The moved and new tooling
lives in `tests/`, which runtime modules must never import
(`tests/test_integration_tool_boundaries.py`); the inward layer contracts in
`pyproject.toml` (`uv run lint-imports`) and `tests/test_architecture.py` remain the
package's contracts. The new lifecycle module is added to the boundary test:
standard library only, so that it runs before the k8s-infra environment is
resolved, with a negative case that rejects a `cveta2` or SDK import.

## Verification

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`,
  `uv run vulture`, `uv run lint-imports`
- `uv run pytest tests/test_architecture.py tests/test_integration_tool_boundaries.py tests/test_integration_lifecycle.py tests/test_mutation_tool.py tests/test_docs.py`
- the full pre-commit suite on each commit
- version-drift entry by hand: matching and mismatching versions
- live: `lifecycle up` → targeted `lifecycle test` → `lifecycle stop`, with
  exact-tag cleanup listings
- pre-push: full mutation profile and the new integration gate, not skipped
- fresh independent review of the whole diff before the push

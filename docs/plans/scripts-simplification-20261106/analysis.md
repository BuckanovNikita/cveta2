# scripts/ simplification analysis

Date: 2026-11-06. Status: proposal, not implemented. Branch at analysis time:
`project-cleunap` (HEAD `66b431b`).

Goal: drop or fold files in `scripts/` by replacing them with standard pre-commit
hooks, moving them next to their only consumer, or changing the workflow so they
are no longer needed.

## Current inventory

16 tracked files, about 2,750 lines of code, plus `README.md`.

| File | Wired into |
|---|---|
| `check_architecture.py` | pre-commit hook `architecture-effects`; imported by `tests/test_architecture.py` |
| `check_commit_msg.py` | commit-msg hook `conventional-commit`; `commit` skill |
| `check_version_drift.py` | pre-push hook `version-drift` |
| `mutation_test.sh`, `mutation_gate.py`, `mutation_config.py` | pre-commit `mutmut` (fast profile), pre-push `mutmut-full`; `tests/test_mutation_wrapper.py`; `mutation-testing` skill |
| `integration_env.sh`, `integration_up.sh`, `integration_test.sh`, `integration_stop.sh`, `integration_gate.sh` | pre-push `integration-tests`; `tests/test_integration_env.py`; CONTRIBUTING; `running-integration-tests` skill |
| `benchmark_fetch.py` | reproduction harness cited by `specs/001-fetch-speed-diagnostics/evidence/benchmark.md` |
| `clone_project_to_s3.py` | loaded by path in `tests/integration/test_review_remediation.py`; referenced by a docstring in `cveta2/adapters/cvat/storage.py` |
| `upload_dataset_to_cvat.py` | no references outside `scripts/README.md` |
| `export_cvat_fixtures.py` | one CONTRIBUTING line |
| `__init__.py` | needed for `from scripts.check_architecture import ...` and `python -m scripts.benchmark_fetch` |

`scripts/__pycache__/` is gitignored. No CI exists (`.github/` is absent), so the git
hooks are the only gates.

## Agent hooks are not a replacement

Claude and Codex hooks fire only inside agent sessions. A human running `git commit`
or `git push` would bypass every gate. Each hook would also have to be written and
synchronized twice, once per host. The gates stay as git hooks run by pre-commit.
Agent hooks fit only agent-specific rules, for example "do not hand-edit
`project.version`".

## Per-file options

| File(s) | Replacement | What is lost |
|---|---|---|
| `check_commit_msg.py` | Off-the-shelf `compilerla/conventional-pre-commit` hook (or commitizen `cz check`), given the same 10 commit types | The custom rule that a `!` subject must carry a `BREAKING CHANGE:` footer. Without it, a breaking change still bumps the version, but its changelog entry has no text. |
| `check_version_drift.py` | Inline pre-push entry: `bash -c '[ "v$(uv version --short)" = "$(git describe --tags --abbrev=0)" ]'` | Nothing important; the error message gets shorter. The no-tag case needs a guard. Alternative: version from git tags (hatch-vcs, PSR without `version_toml`), which makes drift impossible but changes the version strings of dev builds. Not recommended now. |
| `check_architecture.py` | Move into `tests/` (for example into `test_architecture.py`, which already imports it); drop the separate `architecture-effects` hook, because the pytest hook runs on every commit | Nothing |
| `upload_dataset_to_cvat.py`, `export_cvat_fixtures.py` | Delete both, together with their README and CONTRIBUTING sections. They form one pipeline: create coco8 in CVAT, then snapshot it into `tests/fixtures/cvat/coco8-dev/`. Those fixtures have not changed since 2026-02-12, and stand seeding uses `tests/integration/seed_cvat.py`. | The ability to regenerate the coco8-dev fixtures from a live CVAT |
| `clone_project_to_s3.py` | Its only real consumer is `test_review_remediation.py`. Move it into `tests/integration/` and reuse `cveta2.adapters.cvat.storage.parse_cloud_storage` instead of its duplicate `CloudStorageInfo`/`parse_cloud_storage`; or delete the script together with that test | Nothing if moved; that test coverage if deleted |
| `mutation_test.sh`, `mutation_gate.py`, `mutation_config.py` | No stock replacement: `mutmut run` always exits 0 and has no threshold or per-mutant allowlist. Merge into one `scripts/mutation.py` with `run`, `gate` and `sync-scope` subcommands. | Nothing; two fewer files. Behaviour to preserve: an empty profile means a bare `mutmut run` (cache reuse), scope-fingerprint wipe of `mutants/`, allowlist narrowing by glob, stripping the CR spinner when stdout is not a TTY. |
| `integration_*.sh` (5 files) | pre-commit cannot own the stand lifecycle (tag, seed, test, keep-or-stop). Real simplification: move up/stop into a session fixture in `tests/integration/conftest.py` and env resolution into Python, so the gate becomes a plain `pytest tests/integration` behind an "armed" check. Cheaper option: merge into one `integration.sh up\|test\|stop\|gate`. | Regression risk in the area spec 005 recently hardened |
| `benchmark_fetch.py` | Keep. Optionally move under `specs/001-fetch-speed-diagnostics/` so `scripts/` holds only gates. | — |

## Tiers

- **Tier 1, low risk:** the commit-message check, version drift, the architecture
  check, deleting the upload/export pair, and moving `clone_project_to_s3.py`.
  Result: 10 tracked files and one fewer custom hook.
- **Tier 2:** Tier 1 plus merging the three mutation files into one. Result: 8 files.
- **Tier 3:** Tier 2 plus moving the integration lifecycle into pytest fixtures.
  Result: about 3 files, but it is a rewrite.
  Amended in [plan.md](plan.md): a Python lifecycle CLI under `tests/integration/`
  replaces the fixture idea, because `tests.env_isolation` swaps HOME at pytest
  start-up and the gate's preflight must run outside pytest.

## Independent small cleanups (any tier)

- `scripts/README.md` is stale:
  - It names `cveta2._client.dtos`; the current module is `cveta2.application.ports.dtos`.
  - The mutation example `'cveta2.dataset_partition.*'` targets a 9-line compatibility
    re-export that is not in `only_mutate`, so it matches nothing. Use a real module,
    for example `cveta2.domain.partition.*`.
  - The "other scripts" table omits `check_architecture.py` and `benchmark_fetch.py`.
- `from __future__ import annotations` appears in `upload_dataset_to_cvat.py`,
  `export_cvat_fixtures.py`, `clone_project_to_s3.py`, `check_commit_msg.py`,
  `check_version_drift.py`, `mutation_config.py` and `mutation_gate.py`. The owner's
  rules forbid it, and on Python >=3.12 removing it is mechanical.
- `upload_dataset_to_cvat.py` imports three private package helpers (`_load_yaml`,
  `_parse_label_file`, `_normalize_class_names`), and its label parser checks class
  IDs before calling the package parser, which checks them again. This is moot if
  the file is deleted.

## Open decisions

1. Which tier to implement.
2. Whether losing the "`!` requires a `BREAKING CHANGE:` footer" rule is acceptable,
   or whether `check_commit_msg.py` stays.
3. For `clone_project_to_s3.py`: move it into `tests/integration/`, or delete it
   together with `test_clone_real_task_specific_frames`.

## Impact on the implementation process

Any tier changes `.pre-commit-config.yaml`, `CONTRIBUTING.md`,
`.specify/memory/engineering.md` and `architecture.md`, and the `commit`,
`mutation-testing` and `running-integration-tests` skills. Per the repository rules
it goes through the Spec Kit flow (specify, plan, tasks, implement) with a
module-architecture record. Verification: all pre-commit hooks, the pre-push
mutation gate, and the live integration gate.

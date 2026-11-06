# Verification evidence: scripts/ simplification (2026-11-06)

Branch `project-cleunap`. Commits: `89b607d` (Tier 1), `28eeedd` (Tier 2 and the
owner-requested removal of `CONTRIBUTING.md` and `LICENSE`), Tier 3 commit after
this file.

## Concurrent work in the checkout

Other agent sessions worked in the same checkout during this task. They deleted
`CONTRIBUTING.md` and `LICENSE` and staged those deletions. The owner confirmed
the deletions were intended and asked for them to be committed with this work;
`28eeedd` carries them and repoints the links.

## Tier 1

- Version-drift entry, run by hand from `.pre-commit-config.yaml`: matching
  version passed (`Version 0.13.1 matches tag v0.13.1.`, exit 0); a substituted
  `9.9.9` failed with the guidance text (exit 1); a repository with no tag passed
  (`No tag reachable from HEAD.`, exit 0).
- `conventional-pre-commit` v4.5.0 behaviour was taken from its source at that
  tag (non-strict mode exempts merge and autosquash subjects). Running the
  downloaded package standalone was refused by the session's permission
  classifier; the hook then ran on every commit of this task and accepted the
  subjects.
- `uv run pytest -n 0 tests/test_review_dataset.py tests/test_architecture.py`:
  220 passed. Full pre-commit suite on `89b607d`: all hooks passed.

## Tier 2

- `uv run pytest -n 0 tests/test_mutation_tool.py`: 11 passed (profile
  resolution before work, bare run for the empty profile, argument pass-through,
  verdict pass, escaped survivor, stale allowlist entry, missing stats, failing
  run, spinner stripping, scope-change wipe).
- The pre-commit `mutmut` hook ran through the new
  `uv run python scripts/mutation.py --profile fast` on `28eeedd` and passed.

## Tier 3

- `uv run pytest -n auto tests/test_integration_lifecycle.py`: 61 passed (the
  shell suite's cases ported one for one, plus up, gate-failure teardown, env
  evaluation and malformed helper output).
- `uv run pytest -n 0 tests/test_integration_tool_boundaries.py`: 13 passed,
  including the lifecycle standard-library contract and its negative cases.
- `uv run pytest -n auto tests`: 2815 passed.
- `uv run ruff check`, `uv run ruff format --check` and `uv run mypy` on `tests/`
  and `scripts/`: clean. `uv run pytest -n 0 tests/test_docs.py`: 14 passed.
- Live, `infra.py room` GO, `INFRA_HARNESS=claude`:
  - `lifecycle up` minted `cveta2-claude-20261106-integration-03d1`, verified
    the identity, cleared the tag, seeded project id 53, exit 0;
  - `lifecycle test tests/integration/test_review_remediation.py
    tests/integration/test_clearml.py`: 5 passed (ClearML whoami first;
    exercises the moved clone helper), exit 0;
  - `lifecycle stop`: CVAT data removed, bucket deleted (13 objects), ClearML
    nothing to clean, `.run-tag` released, exit 0;
  - exact-tag listings afterwards: CVAT `0 project(s), 0 task(s), 0 storage(s)`,
    MinIO `0 bucket(s)`, ClearML `0 project(s), 0 task(s)`.

The pre-push gates (full mutation profile and `lifecycle gate`) are recorded
with the push.

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

## Independent review and fixes

A fresh general-purpose reviewer read the whole diff `66b431b..f2755c8` against
the originals (read-only, no live services). Verdict: no blockers; one major and
seven minor findings, all addressed in the follow-up commit:

1. Major, interrupting the gate could orphan pytest: `subprocess.run` kills its
   child on any exception, so teardown raced pytest's own cleanup. Children now
   run through `lifecycle.call`, which waits for the child (forwarding SIGTERM)
   before re-raising. `test_an_interrupted_gate_lets_pytest_finish_before_tearing_down`
   covers SIGTERM and a group-wide SIGINT; the SIGTERM case fails when the old
   kill-on-exception behaviour is restored and passes with the fix. The SIGINT
   case cannot tell the two apart (the whole group receives the signal at once)
   and stays as a behaviour check.
2. `.env` parsing: `$VAR`, `~` and inline comments now work; unbalanced quotes
   are a refusal, not a traceback (also for helper output).
3. Gate output order: a failing step is reported, then the FAILED block, then
   the teardown, matching the shell gate.
4. `scripts/mutation.py` runs mutmut from the repository root, passes a failing
   `mutmut run` status through, and no longer hides `mutmut results` stderr.
5. Tests: the real `fast`/`full` profiles must resolve; exit-status passthrough;
   `MINIO_BUCKET` and the project name after `up`.
6. Additional commit-msg losses (blank line before a body, scope characters) are
   recorded in plan.md and the `commit` skill.
7. Stale text: `specs/baseline.md` scripts row, the `also_copy` comment, the
   `tests/test_docs.py` Russian-docs rule.
8. `lifecycle env` refuses to print credentials to a terminal.

After the fixes: `uv run pytest -n auto tests` 2824 passed; `ruff check`,
`ruff format --check`, `mypy .`, `vulture` clean; `lint-imports` 10 kept,
0 broken. The architecture review is accepted on the reviewer's verified list
(effect checker still runs on the real package, lifecycle stdlib-only contract,
no runtime module imports tooling) plus these fixes.

Out of scope, reported: the separate k8s-infra repository still names
`integration_up.sh` in `projects.toml:160` and `references/minio-stand.md:169`
comments.

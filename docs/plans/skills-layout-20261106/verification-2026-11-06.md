# Verification: project skills layout, 2026-11-06

Run on branch `project-cleunap` from base `ef9cf6e`.

## Layout

- `git ls-files -s .claude/skills` lists `mutation-testing`, `release` and
  `running-integration-tests` with mode `120000`. Each target is
  `../../.agents/skills/<name>`.
- The sources are tracked regular files under `.agents/skills/<name>/`.
- An edit made through `.agents/skills/running-integration-tests/SKILL.md` was
  read back through the `.claude/skills` path.
- Claude Code discovered the new `release` skill through its symlink as soon as
  it was created.
- `speckit-*` pairs:
  - The per-host copies differ only in the `/` and `$` invocation sigils and in the
    Claude-only `argument-hint`, `user-invocable` and `disable-model-invocation`
    keys.
  - `specify integration upgrade codex` and `specify integration upgrade claude`
    (specify 1.0.13) regenerated them byte-identically; only the `installed_at`
    timestamps in both manifests changed.
  - `specify integration status` reports 0 modified, missing or invalid managed
    files.
  - A newer CLI (1.3.1) exists; the CLI was not upgraded.

## Checks

- `uv run pytest -n 0 -q tests/test_docs.py`: 26 passed.
- Negative checks of the new `TestProjectSkillsShareOneSource`, each reverted
  afterwards:
  - Adapter pointing elsewhere and a missing `SKILL.md`: the symlink test failed.
  - `release` exceptions removed from `.gitignore`: the gitignore test failed.
  - Tracked `mutation-testing` exceptions removed: it also failed, because the
    test uses `git check-ignore --no-index`.
  - Untracked personal skill `.agents/skills/zz-personal`: the suite still passed.
  - Stale `speckit-gone` entry injected into the Claude manifest: the manifest test
    failed.
- `uv run pre-commit run --all-files`: see the commit for the final run. Before
  this evidence existed, the only failure was the dead link from `tasks.md` to
  this file.
- Architecture record: `validate_architecture.py --phase plan` and
  `--phase acceptance` both exit 0 (no-impact).

## Review

- A fresh general-purpose subagent reviewed the full uncommitted diff read-only.
  The parent resolved every finding:
  - "Never broaden a cleanup selector" was lost; it was restored in engineering
    guidance § "Shared infra".
  - The SKIP "not a recovery step" nuance was restored in § "Hooks".
  - The mutation hook's failure wording now names the failing clean test run.
  - `AGENTS.md` now points at the `release` skill for release commands.
  - Authored skills are derived from `git ls-files`, so personal skills are
    ignored.
  - `check-ignore` now uses `--no-index`.
  - Manifest keys must equal the existing `speckit-*` files.
- Reconciliation with the staged diff:
  - removed: `.claude/skills/commit` and the three old `.agents/skills` symlinks;
  - moved to `.agents/skills`: `mutation-testing` and `running-integration-tests`
    (modified);
  - added: `.agents/skills/release` and three `.claude/skills` symlinks;
  - modified: `.gitignore`, both Spec Kit manifests (timestamps only),
    `engineering.md`, `AGENTS.md` and `tests/test_docs.py`;
  - added: this plan directory.
- No `cveta2/` runtime module changed, so neither the mutation hook nor the live
  integration gate applies.

## Spec Kit 1.3.1 upgrade

- `specify self upgrade --dry-run` resolved the uv tool install method and the
  target v1.3.1; `specify self upgrade` then upgraded 1.0.13 to 1.3.1.
- Before `--force`, every entry in the speckit (12), claude (10) and codex (10)
  manifests matched its file hash.
- The regenerated files are:
  - the `speckit-specify` skills, which now read templates through
    `resolve-template.sh`;
  - the six `.specify/scripts/bash` scripts;
  - `.specify/.gitignore`, which ignores executable adapter packages;
  - the version fields and the three manifests.

  `speckit-taskstoissues` was removed upstream. `.specify/templates` did not change.
- The forced reinstall cleared the execute bit on the six scripts (100755 to
  100644). It was restored with `chmod +x`, and `git diff --summary` shows no mode
  change.
- `check-prerequisites.sh --json --paths-only` resolves the active feature.
- `specify integration status` reports 0 modified, missing or invalid managed files.
- `uv run pytest -n 0 -q tests/test_docs.py`: 26 passed against the new manifests.

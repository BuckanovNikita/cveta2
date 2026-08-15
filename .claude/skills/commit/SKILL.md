---
name: commit
description: >
  Use when the user wants to commit and push code changes. Handles the full
  commit workflow: updating docs, staging files, creating a conventional commit
  through the quality gate, fixing what the hooks report, and pushing via SSH.
  Trigger on: "commit", "push", "/commit".
---

# Commit Workflow

## 1. Review changes

Run `git diff --stat` and `git status` to understand what changed.

## 2. Update documentation

Review the change and update the docs it invalidates — README.md, CONTRIBUTING.md,
ARCHITECTURE.md, and the other `.md` files at the repo root.

## 3. Stage and commit

```bash
git add -A  # or stage selectively
git commit -m "<type>: <description>"
```

`git commit` runs the quality gate; there is no separate step for it. Unstaged
changes are stashed for the run, so what gets checked is what gets committed.
`.pre-commit-config.yaml` is the source of truth for which hooks run and in what
order — read it there rather than trusting a list written here.

A hook that rewrites files (`ruff format`, `uv lock`) aborts the commit. Re-`git
add` the rewritten files and commit again.

The `commit-msg` hook rejects a subject semantic-release cannot parse, so use
[Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` — new feature
- `fix:` — bug fix
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or updating tests
- `docs:` — documentation only
- `chore:` — maintenance (deps, config, CI)

Keep the subject line concise. Use the body for details when needed. A breaking
change needs both the `!` marker and a `BREAKING CHANGE:` footer.

## 4. Fix failures

- **ruff** — `uv run ruff check --fix .` clears the autofixable ones; fix the rest by hand
- **mypy** — the project is `strict = true`, so every new symbol needs annotations
- **import-linter** — the contracts live under `[tool.importlinter]` in `pyproject.toml`;
  read the failing contract's layers there rather than guessing at the hierarchy
- **vulture** — delete the dead code, or whitelist it when the finding is a false positive
- **pytest** — tests run in parallel (`-n auto`); fix failures instead of skipping them
- **mutmut** — a surviving mutant means a test asserts too little; strengthen the
  assertion rather than deleting the mutant. See the `mutation-testing` skill

Commit again once they pass. To see the whole gate without making a commit:
`uv run pre-commit run --all-files`.

## 5. Push via SSH

```bash
git push
```

The remote must use SSH format (`git@github.com:<org>/<repo>.git`). If it is
HTTPS, fix it with:

```bash
git remote set-url origin git@github.com:<org>/<repo>.git
```

The push fires its own gates: the full mutation scope, `version-drift`, and —
on a machine with `tests/integration/.env` — the integration suite against a
stack the hook builds and tears down itself. That last one costs minutes and
destroys any stack you had running. Skip just it with
`SKIP=integration-tests git push`.

## Use `--no-verify` only as a last resort

Always prefer fixing the failure over skipping the hooks.

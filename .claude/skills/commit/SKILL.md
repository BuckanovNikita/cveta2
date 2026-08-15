---
name: commit
description: >
  Use when the user wants to commit and push code changes. Handles the full
  commit workflow: running the pre-commit quality gate, updating docs, staging
  files, creating a conventional commit, and pushing via SSH.
  Trigger on: "commit", "push", "/commit".
---

# Commit Workflow

## 1. Review changes

Run `git diff --stat` and `git status` to understand what changed.

## 2. Run the quality gate

```bash
uv run pre-commit run --all-files
```

`.pre-commit-config.yaml` is the source of truth for which hooks run and in what
order — read it there rather than trusting a list written here.

If pre-commit fails because of unstaged changes, stash first:

```bash
git stash
uv run pre-commit run --all-files
git stash pop
```

If a formatter rewrote files, re-stage them and re-run.

## 3. Fix failures

- **ruff** — `uv run ruff check --fix .` clears the autofixable ones; fix the rest by hand
- **mypy** — the project is `strict = true`, so every new symbol needs annotations
- **import-linter** — the contracts live under `[tool.importlinter]` in `pyproject.toml`;
  read the failing contract's layers there rather than guessing at the hierarchy
- **vulture** — delete the dead code, or whitelist it when the finding is a false positive
- **pytest** — tests run in parallel (`-n auto`); fix failures instead of skipping them
- **mutmut** — a surviving mutant means a test asserts too little; strengthen the
  assertion rather than deleting the mutant. See the `mutation-testing` skill

Re-run until every hook passes.

## 4. Update documentation

Review the change and update the docs it invalidates — README.md, CONTRIBUTING.md,
ARCHITECTURE.md, and the other `.md` files at the repo root.

## 5. Stage and commit

```bash
git add -A  # or stage selectively
git commit -m "<type>: <description>"
```

Use [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` — new feature
- `fix:` — bug fix
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or updating tests
- `docs:` — documentation only
- `chore:` — maintenance (deps, config, CI)

Keep the subject line concise. Use the body for details when needed.

## 6. Push via SSH

```bash
git push
```

The remote must use SSH format (`git@github.com:<org>/<repo>.git`). If it is
HTTPS, fix it with:

```bash
git remote set-url origin git@github.com:<org>/<repo>.git
```

## Use `--no-verify` only as a last resort

Always prefer fixing the failure over skipping the hooks.

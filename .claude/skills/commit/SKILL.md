---
name: commit
description: Commit or push a reviewed set of cveta2 changes when the user asks. Preserves unrelated working-tree work, stages exact intended paths, uses Conventional Commits, handles hook rewrites and failures, and runs push gates without silently bypassing them.
---

# Commit cveta2 changes

Create the requested commit from the intended change set while preserving every
unrelated working-tree change. A request to commit does not imply a push; push
only when the user asks for it.

## Establish the change set

Inspect before staging:

```bash
git status --short --branch
git diff -- <intended paths>
git diff --cached
git remote -v
```

Identify which modified and untracked paths belong to the current task. Existing
changes outside that set remain untouched. If ownership is unclear, use the
conversation and earlier status snapshots; ask only when ambiguity could place
someone else's work in the commit.

Update documentation only when the change invalidates it. CLI or public API
changes normally require the Russian user docs and their index; architecture or
data-format changes require their named documents. A docs-only change does not
require unrelated code edits.

## Stage exact paths

Use `git add -- <path>...` for the intended files. Never use `git add -A`,
`git add .`, a broad glob, or a manual stash. Pre-commit may temporarily stash
unstaged changes as part of its own isolation; leave that to the hook.

Review the actual candidate:

```bash
git diff --cached --stat
git diff --cached
```

Confirm it contains only the intended changes and no credentials, generated
artifacts, integration `.env`, mutation workspace, or unrelated edits.

## Commit

Use a Conventional Commit subject accepted by
`scripts/check_commit_msg.py`: `feat:`, `fix:`, `refactor:`, `test:`,
`docs:`, or `chore:`. Add a body when it helps explain behavior or
tradeoffs. A breaking change requires both the `!` marker and a
`BREAKING CHANGE:` footer.

`git commit` runs the configured hooks. Read `.pre-commit-config.yaml` for
the current gate rather than copying its list here. If a hook rewrites files,
inspect the new diff and restage only task-owned paths before retrying. If a hook
fails because of unrelated pre-existing work, report the exact blocker; do not
modify, stage, stash, or discard that work.

Do not use `--no-verify` unless the user explicitly asks to bypass hooks.
After success, read back the commit summary and verify that unrelated changes
remain in the working tree.

## Push only when requested

The repository convention is an SSH remote. Inspect it, but do not rewrite an
HTTPS or unexpected remote automatically. Push the requested branch/ref with
plain `git push` when its configured upstream is correct, or name the explicit
ref when needed.

Pre-push runs the full mutation profile, version-drift check, and, when
`tests/integration/.env` exists, a live integration gate. That gate recreates
MinIO/ClearML and exact-tag CVAT objects according to the
`running-integration-tests` skill. A push request authorizes the configured
hooks; if a hook cannot run, report the failure. Use
`SKIP=integration-tests` only when the user explicitly requests that skip.

Git opens the SSH transport before the pre-push hooks run, and the gates
outlast GitHub's idle timeout. The clone must therefore carry
`core.sshCommand "ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=40"`
(the CONTRIBUTING quick start sets it); check with
`git config --get core.sshCommand` before a gated push and set it when
missing. A push that ends with `Connection to github.com closed by remote
host` after green hooks delivered nothing: verify with
`git ls-remote origin <refs>` and simply push again with the keepalive in
place. Never shorten the gates with `SKIP` to work around this.

Return the commit hash and subject, pushed ref if any, checks run by the hooks,
and the remaining unrelated working-tree state.

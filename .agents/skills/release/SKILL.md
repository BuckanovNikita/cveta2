---
name: release
description: Cuts a cveta2 release on main with semantic-release right after a merge - previews the version, bumps pyproject.toml, uv.lock and CHANGELOG.md, creates the release commit and Git tag through the pre-commit hooks (including the live gate in the cveta2-main slot), pushes and confirms them. Use after merging into main, when semantic-release fails or stays silent, or when a release hook fails and leaves bumped files staged.
---

# Release cveta2

Release policy (merge-only `main`, semantic-release as the only version writer,
Git tags only, authorization) is in engineering guidance § "Commits, hooks, and
releases". This skill is the procedure.

## Steps

Run on `main`, right after the merge, from a clean working tree:

```bash
uv run semantic-release version --print                     # the version it would make
uv run semantic-release version --no-push --no-vcs-release  # bump, changelog, commit, tag
git push origin main --follow-tags                          # push the checked commit and tag
git ls-remote origin refs/heads/main refs/tags/vX.Y.Z       # confirm it landed
```

- `No release will be made` after a merge of only non-releasing types is a
  success; push `main` alone and stop.
- The release commit touches `pyproject.toml`, `uv.lock` and `CHANGELOG.md`, so
  pre-commit runs the live integration gate in the durable `cveta2-main` slot
  (see the `running-integration-tests` skill). semantic-release captures hook
  output: expect minutes of silence.

## A hook fails

The commit and tag are not created, but the bumped version files stay staged.
Read the error, then restore them and fix the cause before releasing again:

```bash
git restore --staged --worktree pyproject.toml uv.lock CHANGELOG.md
```

Never hand-edit the version or create the tag yourself. `SKIP=integration-tests`
only on the user's explicit request.

## Report

The released version (or "no release"), the release commit and tag confirmed by
`git ls-remote`, the hooks that ran, and any failed or skipped gate as a gap.

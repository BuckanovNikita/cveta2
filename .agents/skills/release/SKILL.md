---
name: release
description: Merges a checked cveta2 branch into main by fast-forward and cuts the release with semantic-release under a release lock - full check on the branch tip, ff-only merge, version bump, changelog and Git tag with the heavy hooks skipped, push and confirmation. Use when a branch is ready to land on main, when semantic-release fails or stays silent, or when a release hook fails and leaves bumped files staged.
---

# Merge and release cveta2

Release policy is in engineering guidance § "Commits, hooks, and releases":
- `main` changes only by fast-forward merge;
- semantic-release is the only writer of the version;
- only Git tags are published;
- authorization rules apply.

This skill is the procedure. `BRANCH` is the branch to land.

## 1. Check the branch tip

On `BRANCH`, with a clean working tree:

```bash
git fetch origin
git rebase origin/main                 # skip when already on top of main
uv run prek run --all-files            # every hook over the whole tree
uv run pytest --cov                    # full suite, live tests included, coverage enforced
HYPOTHESIS_PROFILE=explore uv run pytest -m "not integration" -p no:randomly  # random property inputs
```

- **After the rebase,** if it rewrote commits, the commit hooks did not run on
  them. The two checks above are what covers them.
- **Live tests may wait for stopped stands,** with a notice. Run the full suite
  in the background and tell the user it is waiting; never skip it.
- **Every check must pass** before step 2.

## 2. Merge, release and push under the lock

```bash
git switch main
flock -n "$(git rev-parse --git-common-dir)/cveta2-release.lock" bash -c '
  set -e
  git fetch origin
  git merge --ff-only origin/main      # catch up with what other sessions pushed
  git merge --ff-only "$1"             # land the checked branch
  uv run semantic-release version --print
  SKIP=lint-imports,mypy,vulture,pytest uv run semantic-release version --no-push --no-vcs-release
  git push origin main --follow-tags
' _ "$BRANCH"
git ls-remote origin refs/heads/main 'refs/tags/v*' | tail -3   # confirm it landed
```

- **The lock.** `flock -n` fails at once when another session holds the lock.
  Report that and retry after that session's release, instead of waiting
  silently.
- **The merge is refused.** `--ff-only` refuses when `origin/main` moved past
  the branch's base. Nothing was tagged; return to step 1: rebase and check
  again.
- **No release.** `No release will be made` after a merge of only non-releasing
  types is a success; the push publishes `main` alone.
- **The skip.** The release commit touches `pyproject.toml`, `uv.lock` and
  `CHANGELOG.md` on an already-checked tree. The `SKIP` list is the documented
  exception. Ruff, `uv lock --check`, the lockfile guard, deptry and `uv build`
  still run.

## A release hook fails

The commit and tag are not created, but the bumped version files stay staged.
Read the error, then restore them and fix the cause before releasing again:

```bash
git restore --staged --worktree pyproject.toml uv.lock CHANGELOG.md
```

Never hand-edit the version or create the tag yourself. Never widen the `SKIP`
list beyond the one above.

## Report

- The merged range and the full-check results from step 1.
- The released version, or "no release".
- The release commit and tag, confirmed by `git ls-remote`.
- Any failed, skipped or waiting gate, reported as a gap.

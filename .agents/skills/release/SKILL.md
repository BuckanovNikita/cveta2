---
name: release
description: Integrate an accepted cveta2 tip by fast-forward and evaluate semantic-release under the shared release lock. Use for releases, blocked acceptance, explicit release-check failures, or staged version/changelog/lockfile recovery.
---

# Merge and release cveta2

[Engineering guidance](../../../.specify/memory/engineering.md#releases) owns policy.
Semantic-release owns versions, changelog and tags. Publish Git version tags only.
`BRANCH` below names the branch to land. Push authorization is separate.

## 1. Accept the clean branch tip

Fetch and rebase if needed, inspect load and choose `CVETA2_TEST_WORKERS`. On the
clean committed branch, with `SKIP` cleared:

```bash
git fetch origin
git rebase origin/main
uv run --locked task --exit-code acceptance
```

Skip an unnecessary rebase. Acceptance includes static checks, packaging,
randomized properties and full-suite live coverage; do not repeat those stages
or run affected units immediately beforehand. Code changes also require the
`mutation-testing` skill's branch comparison and fresh independent review after
integration and verification. A rewritten or changed tip needs checks for the new
inputs. Record the accepted tip and outcomes in the release-attempt report.

Use `running-integration-tests` for bounded preflight and cleanup. UNAVAILABLE/3
means deferred verification, ERROR/1 means diagnosis is required. Continue useful
independent work; retry at a meaningful milestone or after restored availability.
When only blocked verification remains, stop and ask for the user's decision.
Every required check must pass before integration. Live acceptance is reusable
only within this same release attempt on the unchanged clean branch tip.

## 2. Merge, release and push under the lock

Proceed only with separate authorization to push `main` and the release tag;
otherwise stop after the concrete acceptance result. Set `ACCEPTED_TIP` to the
commit just accepted; do not infer acceptance from a branch name or old cache.

```bash
git switch main
flock -n "$(git rev-parse --git-common-dir)/cveta2-release.lock" bash -c '
  set -e
  test "$(git rev-parse "$1")" = "$2"
  test -z "$(git status --porcelain)"
  git fetch origin
  git merge --ff-only origin/main
  git merge --ff-only "$1"
  test "$(git rev-parse HEAD)" = "$2"
  uv run --locked semantic-release version --print
  CVETA2_RELEASE_CHECK=1 SKIP=verify uv run --locked semantic-release version --no-push --no-vcs-release
  git push origin main --follow-tags
' _ "$BRANCH" "$ACCEPTED_TIP"
git ls-remote origin refs/heads/main 'refs/tags/v*'
```

The lock covers merge through push. Lock contention is a reported blocker, not
permission to start a concurrent release. If a fast-forward fails or the accepted
tip no longer matches, return to step 1; do not tag a different tip. A no-release
decision is successful evaluation and publishes only `main` when authorized.

`CVETA2_RELEASE_CHECK=1` explicitly invokes
`uv run --locked task --exit-code release-check` from semantic-release's build
command after its version/changelog/lockfile updates and before committing.
The task permits only those release paths and runs lock, read-only Ruff,
dependency and packaging checks. `SKIP=verify` is the documented release exception;
Conventional Commit validation and staging guards remain active. Never use the
exception for other content or infer it from the branch name.

## Failed release recovery

A failed build/check may leave task-owned version, changelog and lockfile changes
staged without a release commit or tag. Inspect `git status`, the staged diff and
actual tags before recovery; establish which changes this attempt created. Restore
only those owned changes when returning to the accepted tip, fix the cause on the
branch and repeat affected verification. Do not hand-edit the version or tag, widen
the exception, discard unrelated work or claim a partially created release passed.

## Report

Report the accepted and merged tips, required check outcomes, mutation findings,
release version or no-release decision, and actual release commit/tag. Confirm
pushed refs remotely. Distinguish failures, deferred checks and cleanup leftovers.

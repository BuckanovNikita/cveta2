---
name: release
description: Use when preparing a cveta2 PR for merge into main, inspecting the automatic release after a merge, recovering a failed release workflow run, or when a release is requested.
---

# Merge readiness and automatic releases

Paths start at the repository root. `docs/development.md#releases` describes the release
workflow, what a release changes and publishes, the recovery states and the never-list.
A request for a release is answered by preparing a PR for a human merge, never by a local
release.

## Before merge

1. Check the issue's Verification section with `verification-workflow`: every kept line
   has a status, and none is deferred, failed or error unless the user waived it.
2. Read the PR title and the commit headers that will land in the squash body. Correct
   any type that does not match the release the change should get
   (`docs/development.md#commit-procedure`). Optionally confirm with the dry run in
   `docs/development.md#releases`. Done when the expected version effect is stated in the
   PR or the Linear issue.
3. Report the PR as ready for a human merge. Done when the issue links the PR and the
   verification statuses.

## After merge

4. Open the `Release` workflow run for the merge (`gh run list --workflow release.yml`,
   then `gh run view <run-id> --log`) and record on the Linear issue the fields
   `docs/development.md#releases` lists. Done when the issue states the version or the
   "No new version" result. The release job establishes no test, live or packaging
   outcome.

## Recovering a failed run

5. Read the run log and the remote refs
   (`git ls-remote origin refs/heads/main 'refs/tags/v*'`) before rerunning anything.
6. Match the state to `docs/development.md#recovery-states` and follow it; report a
   release commit without its tag at once.
7. Record the recovery and its outcome on the Linear issue.

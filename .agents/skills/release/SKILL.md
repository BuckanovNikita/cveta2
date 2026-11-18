---
name: release
description: Use when preparing a cveta2 PR for merge into main, inspecting the automatic release after a merge, recovering a failed release workflow run, or when a release is requested.
---

# Automatic releases

Paths start at the repository root. `docs/agents/engineering.md#releases` describes the
release workflow, what its script checks and what it publishes. A human merge of a PR
into `main` is the only release trigger and its authorization; a request for a release
is answered by preparing a PR for that merge, never by a local release.

## Before merge

1. Read the PR title and the commit headers that will land in the squash body. Only
   `feat`, `fix`, `perf` and `!` move the version, and the parser reads every body
   paragraph that starts like a Conventional Commit header. Correct any type that does
   not match the release the change should get. Done when the expected version effect
   is stated in the PR or the Linear issue.
2. Confirm the verification statuses with `verification-workflow`; deferred or failed
   required acceptance blocks merge readiness and therefore release.

## After merge

3. Open the `Release` workflow run for the merge (`gh run list --workflow release.yml`,
   then `gh run view <run-id> --log`). Record on the Linear issue the run URL, the source
   and released SHAs, the version or "No new version" result and the tag identity
   (`git ls-remote origin refs/heads/main 'refs/tags/v*'`). The release job establishes
   no test, live or packaging outcome.

## Recovering a failed run

4. Read the error and the current remote refs before rerunning anything. A rejected
   atomic push changes neither ref. When `main` moved or the connection failed, rerun
   the job on the refreshed `main` (`gh run rerun <run-id>`); an already published
   release reruns as a no-op. A conflicting remote tag needs investigation and a human
   decision before any rerun. If repository rules block the bot's push to `main`, report
   that the release needs bot authorization; do not weaken human protections.
5. Record the recovery and its outcome on the Linear issue.

## Never

- Push `main`, merge locally into `main`, or create, push, move or delete a tag.
- Run `semantic-release` locally in a mode that writes; `--noop` dry runs are fine.
- Force-push, rewrite history or reset unrelated work.
- Publish a GitHub Release, release asset or package.

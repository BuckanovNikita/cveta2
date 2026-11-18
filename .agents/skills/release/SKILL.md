---
name: release
description: Use when preparing a cveta2 PR for merge into main, inspecting the automatic release after a merge, recovering a failed release workflow run, or when a release is requested.
---

# Automatic releases

Paths start at the repository root. `docs/agents/engineering.md#releases` describes the
release workflow and what it publishes. A human merge of a PR
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

semantic-release pushes `main` first and the tag second, as two separate pushes. Before
pushing it checks that remote `main` still equals the commit it released from. Read the
run log and the remote refs (`git ls-remote origin refs/heads/main 'refs/tags/v*'`)
before deciding which state applies.

4. Failed before any push (a build command error, a moved `main`, a rejected branch
   push): nothing is published. The next merge releases everything still unreleased, or
   a human reruns the workflow on the current `main` (`gh run rerun <run-id>`). An error
   in the build command or configuration repeats on every merge; fix it through a PR.
5. The release commit reached `main` but the tag did not: the next run (a rerun or the
   next merge) computes the same version from the last tag, finds `pyproject.toml`,
   `uv.lock` and `CHANGELOG.md` already current, makes no commit, tags the current `HEAD`
   of `main` and pushes only the tag. If other merges landed in between, the tag lands on
   the newer `HEAD`, and a `feat` among them yields a higher version instead, leaving the
   first version untagged. Report the state; only a human creates or pushes a tag by hand.
6. The tag for the computed version already exists: semantic-release prints
   `No release will be made, <version> has already been released!` and exits 0 without a
   commit, tag or push. If that tag is not on `main`, every run that computes the same
   version skips the same way until a human investigates and removes it.
7. Branch protection or repository rules reject the bot's push: report that the release
   needs a bypass for the Actions token; do not weaken human protections. Branch
   protection on `main` without such a bypass blocks every release push.
8. Record the recovery and its outcome on the Linear issue.

## Never

- Push `main`, merge locally into `main`, or create, push, move or delete a tag.
- Run `semantic-release` locally in a mode that writes; `--noop` dry runs are fine.
  Nothing technical stops a local `semantic-release version` from pushing; this rule
  is policy, not enforcement.
- Force-push, rewrite history or reset unrelated work.
- Publish a GitHub Release, release asset or package.

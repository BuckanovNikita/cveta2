---
name: verification-workflow
description: Select cveta2 Task stages for explicit fixes, development verification, commits, clean-tip acceptance and release checks. Use before verifying changes or claiming completion, and when infrastructure defers required verification.
---

# Verification workflow

Policy and definitions live in [engineering guidance](../../../.specify/memory/engineering.md#verification).
`Taskfile.yml` owns commands and ordering. Invoke each stage as
`uv run --locked task --exit-code <name>`; keep failure exit codes.

1. Inspect worktree ownership and load, choose `CVETA2_TEST_WORKERS`, and stop
   concurrent editing before verification. Each worktree owns its tool state.
   Clear inherited `UV_PROJECT_ENVIRONMENT` before the outer `uv run` so it uses
   this worktree's `.venv`; Task then fixes cache paths for its child commands.
2. Run `fix` explicitly before staging; inspect safe fixes and formatting. Stage
   exact task-owned paths. Commit inputs must be fully staged with no nonignored
   untracked files. The Git shim rejects unsuitable inputs before prek runs.
3. Use `verify` for development verification. The normal commit hook invokes it;
   reuse that success when inputs remain unchanged. After an explicitly deferred
   intermediate commit, clear `SKIP` and run it on final content. `test-full` is
   the conservative fallback when affected selection cannot represent an input.
4. Before acceptance, use `mutation-testing` for changed product functions. Run
   `acceptance` on the clean committed tip; it already includes checks, build,
   randomized properties and full-suite live coverage. Do not precede it with an
   equivalent affected-unit run. Follow `running-integration-tests` for live
   lifecycle and cleanup, and `release` for the explicit release exception.
5. Report actual executed/selected checks and distinguish passed, failed,
   deferred and incomplete-cleanup outcomes. A deselected test is not a new test
   execution. An interruption is not success. Task freshness is never proof.

`infra-check` returns AVAILABLE/0, UNAVAILABLE/3 or ERROR/1. Unavailability defers
live verification; keep its task incomplete and continue independent local work.
Retry at a meaningful milestone or after restored availability, without polling.
When only blocked verification remains, report the reason and ask for the user's
decision. Deferred verification blocks acceptance, merge and release. Configuration,
authorization and TLS errors require diagnosis; assertions remain test failures.

Use `properties`, `integration` or `mutation` separately when the relevant change
needs them. None is persistently cached. Reuse successful checks only while their
inputs remain unchanged; live acceptance is reusable solely within the same release
attempt on the unchanged clean tip. Markdownlint remains separate.

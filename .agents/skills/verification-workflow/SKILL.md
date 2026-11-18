---
name: verification-workflow
description: Use when selecting verification for a cveta2 change, committing, reporting completion, deciding whether earlier results can be reused, or when infrastructure defers a required check.
---

# Select and report verification

Paths start at the repository root. `docs/development.md` owns every command, the stage
table and the selection policy; the Verification section of
`docs/agents/issue-template.md` is the checklist you fill in.

1. Record the comparison base (the merge base of the task branch with `main`) and the
   tip in the Linear issue. Done when both SHAs are written there.
2. Copy the template's Verification section into the issue if it is not there, and
   delete every line that does not apply, using `docs/development.md#check-selection`.
   Done when every remaining line is one you will run, defer or ask the user to waive.
3. Prepare the worktree as `docs/development.md#verification` says: clear an inherited
   `UV_PROJECT_ENVIRONMENT`, choose `CVETA2_TEST_WORKERS` from the reported load, and stop
   editing while verification runs.
4. Run `fix`, inspect its changes, stage only task-owned paths and commit by
   `docs/development.md#commit-procedure`; the hook runs `verify`. Done when the final
   committed content has a passing `verify` with `SKIP` cleared.
5. Run the other selected checks in the order of
   `docs/development.md#order-reuse-and-reporting`: the mutation report through
   `mutation-testing`, live checks through `running-integration-tests`, and `acceptance`
   last on the clean committed tip. Reuse an earlier result only while its inputs are
   unchanged, and write the reuse reason next to the line.
6. If infrastructure defers a live check, follow
   `docs/development.md#deferral-of-live-checks`: continue independent work, retry at a
   milestone, and ask for the user's decision when only blocked checks remain.
7. Request the fresh independent review the change requires, after integrated
   verification.
8. Write one status (passed, failed, deferred, waived or error) after every kept line,
   with what actually ran and was selected. Done when no kept line lacks a status.

Use `release` for merge readiness and after-merge inspection.

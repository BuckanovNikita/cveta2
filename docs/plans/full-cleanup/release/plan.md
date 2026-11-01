# Cleanup patch release

Date: 2026-11-01. User objective: make a new verified release.
Source branch: `cleanup/contracts-and-release`, currently `24d1045`.

## Scope and architecture

Complete the outstanding native acceptance/delivery tasks in
[002](../../../../specs/002-nullable-completion/tasks.md),
[003](../../../../specs/003-operational-errors/tasks.md) and the
[maintenance ledger](../tasks.md), preserving completed history.
[architecture.json](architecture.json) records inspected no runtime impact for
release-only metadata/evidence. Existing accepted module records continue to own
the implemented fixes. No new runtime code, dependency updates or hook bypasses.

Remote main and local main were verified at v0.12.0 (`a6b77f2`), with no incoming
divergence. A disposable merge of the source branch succeeded; the maintained
semantic-release configuration calculated 0.12.1 without forced bump flags.

## Required sequence

1. Verify release generation and built-package behavior in a disposable checkout;
   keep its branch/tag isolated from the authoritative repository and remote.
2. Obtain the separately required authorization to restore the missing shared
   integration environment. Infrastructure prerequisites and identities remain
   owned by the authoritative infrastructure scripts, never this repository.
3. Run the mandatory live gate with one owned run tag and prove exact-tag cleanup.
   Reconcile current source, architecture acceptance, review and native ledgers.
4. Commit the scoped release evidence/status through normal hooks. Merge to main
   using an ordinary merge; main changes only by merge.
5. Evaluate semantic-release on main, then run
   `uv run semantic-release version --no-push --no-vcs-release`.
   Review generated version/changelog/lock changes; verify versions, tag target,
   build/install behavior and configured mutation/integration gates.
6. Push the main commit and generated Git version tag together through normal
   hooks; verify remote refs and finish dated delivery/convergence evidence.

No GitHub Release objects, package-registry publication, release assets, service
substitution, deployment outside the specifically approved infrastructure scope,
or edits to unrelated untracked skills. A failed/unavailable gate remains open.

## Verification

Reuse inspected source checks only while source identity remains unchanged.
Packaging checks must exercise generated release metadata and wheel imports/CLI
outside the checkout; supported-interpreter evidence must name actual versions.
Preserve test environment isolation and existing optional-dependency boundaries.
Obtain applicable final review after integration and parent verification.
Preparation-only records may be committed before the live prerequisite is resolved;
that preserves verified rehearsal evidence and does not close final acceptance or
delivery tasks. See [tasks.md](tasks.md) for current status and dated evidence.

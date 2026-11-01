# Release worker guard maintenance

Date: 2026-11-01. This is test-runner maintenance; supported runtime behavior,
test membership, mutation scope/profiles and equivalent-mutant policy stay intact.

The first actual release push was interrupted as a whole (exit 130) after two
worker-floor mutations blocked; it did not publish any refs. Both process groups
were inspected before cancellation, and all owned push descendants stopped.
Remote main remained `a6b77f2`; remote v0.12.1 was absent. Do not count that gate
as passed or its interrupted mutants as killed.

## Observation and proposed change

`configure_workers` is called by the autouse sequential-transfer fixture, so
mutmut associates 2653 tests with it. Cached duration sorting placed the existing
count-floor assertion at index 672. Mutants 6 and 11 change a worker floor from
one to two; both remained asleep with one thread in a futex wait. Their latest
temporary files identify the type-only grimp import-contract probe, before the
count assertion. The precise lock/deadlock mechanism is unconfirmed; forcing
threaded transfers is not established as the blocking call. The configured wall
timeout was approximately 779 seconds per case.

Extend the existing collection guard so the existing worker-floor assertion runs
first, followed by the existing CSV EOF guard. Preserve every selected test and
stable relative order for all other tests. This rejects invalid sequential worker
counts before any test relying on that fixture can proceed. No new tests or
fixture assertions are needed. The bounded independent diagnosis favored this
over adding a production-state assertion to every test setup.

## Architecture and ownership

Only `tests/conftest.py` collection ordering changes. Its existing dependency on
the execution adapter and pytest stays unchanged; no production import, interface,
effect or dependency ownership changes. Production layer/effect contracts and
their negative fixtures remain regression checks. A scoped acceptance probe
applies the existing pure-module policy to the extracted collection hook, with
import/effect negative cases. It makes no claim about production-to-tests
enforcement. The adjacent
[architecture.json](architecture.json) records this test-harness module impact.
The parent owns implementation and verification; a fresh independent read-only
review follows integration. No other agent edits source. There is no useful
independent implementation stream for this small change.

## Cache-invalidation amendment

Inspection also found why every mutation invocation rebuilt its cache: mutmut's
Git change detection treats every untracked non-Python path as changed on every
run. The two pre-existing personal skill links were untracked but not ignored.
Extend the existing `.gitignore` policy for personal skill links with those exact
two paths. Preserve both symlinks and targets. This changes no mutation
configuration, profiles, scope, tests, runtime dependency or equivalent policy.
Verify exact ignore matches, unchanged symlink targets and a subsequent ordinary
full-profile execution that actually reuses results without an invalidation notice.
The installed runner already excludes `.gitignore` itself from invalidation.

## Tasks and acceptance

- [x] W001 Validate the architecture plan before source edits.
- [x] W002 Extend collection ordering; prove unchanged membership and stable
  non-guard ordering with reversed, selected collection inputs.
- [x] W003 Rerun both exact mutations, all worker-configuration mutants and the
  full mutation profile; require zero unexplained results or stale equivalents.
- [x] W004 Run ordinary/static/import/effect/architecture and documentation checks;
  reconcile diff, independent review and architecture acceptance.
- [x] W005 Commit with normal hooks, merge to main, evaluate semantic-release and
  publish main plus the generated Git version tag through all required gates.
- [x] W006 Apply the existing personal-skill ignore policy to the two links;
  prove files preserved and ordinary full-profile cache reuse.

The already generated v0.12.1 tag remains local and immutable. This test-only
change does not change its packaged runtime: compare release/current package
source and wheel bytes. Let semantic-release evaluate the ordinary `test:`/merge
commits; do not force a bump, hand-edit versions, reset or retag. Reconcile final
delivery in the parent release ledger. No portable usage-skill change is needed:
commands, API, configuration, recovery and supported behavior are unchanged from
the inspected published skill commit recorded in the parent evidence.

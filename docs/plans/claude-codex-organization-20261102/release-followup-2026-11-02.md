# Release verification follow-up — 2026-11-02

## Exact candidate and isolation

The reviewed instruction migration remains contributor `039efac` and merge
`d59a63ec96ccbb2f2e400301ec32c9001642fda5` on local main. The original checkout
now contains unrelated managed-dataset feature work, so release verification
used an isolated worktree at that exact main commit with its own locked uv
environment. The original feature branch, index, product files and environment were
not changed. The isolated integration arming file carried only the approved
skill-location key; legacy settings from the original file were not copied.
No credential values were emitted or persisted.

## Infrastructure and native gates

After the separately authorized credential repair, TLS verification remained
enabled. Fresh infrastructure preflight returned GO; CVAT, MinIO and ClearML
`whoami` succeeded as project `cveta2`. Semantic release on exact main reported
that 0.12.1 was already released and correctly created no new tag.

The actual native `git push origin main` ran with the minted tag
`cveta2-codex-20261102-instruction-release-7qbn` and
`INTEGRATION_KEEP_DATA=0`, protecting the durable main slot. Results:

- Version-drift gate passed.
- Full mutation gate failed: 8,118 mutants, 7,833 killed, 283 existing
  equivalent allowlist entries, and two unaccepted timeouts.
- The timeout identifiers are
  `cveta2.adapters.s3.upload.xǁS3Uploaderǁupload__mutmut_22` and
  `cveta2.adapters.s3.upload.xǁS3Uploaderǁupload__mutmut_40`.
- The native live integration gate passed: 37 tests, 380 upstream
  Pyparsing deprecation warnings, 208.50 seconds for pytest. CVAT/MinIO
  setup, ClearML publication checks and native lifecycle teardown all ran.

## Cleanup and publication

The native teardown deleted the owned CVAT project and cloud storage and
the owned MinIO bucket with 15 objects. ClearML had no remaining owned
projects. Independent exact-tag helper listings then reported zero CVAT
projects/tasks/storages, zero MinIO buckets and zero ClearML projects/tasks.
No foreign or durable resources were targeted; no shared stand was deployed
or stopped. Windows-client verification was explicitly skipped by the user.

The push failed because the mutation gate failed. Remote main remains
`9d643792cfcb0abfbef00658a797fcce43b0d628`; the existing v0.12.1 tag is
unchanged. This supersedes the earlier TLS blocker without treating the new
mutation timeouts as passing. No product code, mutation policy, allowlist or
hook was changed or bypassed. Publication needs separately scoped mutation
triage and another fully passing native push.

## Authorized bounded retry and successful publication

The coordinating parent authorized one documented rerun of only the two timeout
mutants with unchanged native budgets. The native `mutation_test.sh` positional
name route exists and was used for exactly those names. Both were killed on
that single rerun: 7,835 of 8,118 mutants killed, 283 existing equivalent entries,
zero timeouts and zero unexplained results. No source, test, timeout setting,
profile, allowlist or gate configuration changed. The original failure above
remains recorded rather than reclassified as a passing run.

A fresh GO preflight and minted tag
`cveta2-codex-20261102-instruction-release-r-5ksp` preceded the actual native
main push retry. With every required hook enabled, version drift, full mutation
and live integration all passed. The second live suite reported 37 passed,
380 upstream deprecation warnings, 217.30 seconds; native integration lifecycle
including setup and cleanup completed in 270.13 seconds.

The native teardown removed the retry's CVAT project and cloud storage and
MinIO bucket with 15 objects. Independent exact-tag listings again reported
zero CVAT projects/tasks/storages, zero MinIO buckets and zero ClearML
projects/tasks. Foreign/durable objects, shared stands and the original dirty
feature checkout were preserved.

`git ls-remote` verified remote main now equals
`d59a63ec96ccbb2f2e400301ec32c9001642fda5`, matching the reviewed local merge.
The annotated v0.12.1 tag object remains
`9135dc69009e3b759b23a1acc15311525b71b5fb`; the docs-only release evaluation
created no new tag. No GitHub Release, package or release asset was published.
The earlier TLS and transient mutation-timeout gates are resolved for this
exact candidate; no library runtime fix is claimed.

## Documentation checks and limitations

The existing no-impact record validates at acceptance. Both changed native
Markdown artifacts pass heading, final-newline, whitespace and local-destination
checks; scoped Git whitespace validation passes. Windows-client verification
was explicitly skipped by the user. This receipt is left as task-owned native
documentation in the active feature checkout; it does not stage or commit any
of that checkout's unrelated changes.

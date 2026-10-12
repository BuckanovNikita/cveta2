# Verification — 2026-10-12

## Baseline and requirements

Base: `3533315` (current main when work started). The triangle with vertices
`(12, 30.5), (90.75, 10.25), (40.5, 80)` produced an unsupported-shape warning
and zero annotations. The original extractor/adapter/cache tests passed (120).

The Spec Kit sequence completed specification, clarification (no unresolved
questions), planning, checklist generation/review, task generation and analysis
before application changes. No extension hooks were registered. The independent
requirements reviewer approved all 10 custom checklist items; the built-in
checklist passed all 16. Analysis mapped every FR to tasks with no blockers.

## Implementation verification

- Extractor/adapter regressions first failed: 16 failures / 60 passes after
  correcting an SDK enum fixture. Final assigned suites: 76 passed.
- Explicit schema-4 local and S3 rejection tests failed before the schema bump;
  cache and polygon-cache suites passed afterward (64 tests).
- Parent public API/CSV/deletion tests initially had a test-helper signature
  error; after correction, all six cases passed against the integrated extractor.
- Affected extractor, SDK, client/fetch, cache, conversion and documentation
  suites: 553 passed.
- Full isolated non-live suite: 2,253 passed; coverage 92.90% (required 90%).
- Ruff check/format, mypy (174 source files), import-linter (4 contracts),
  vulture and `git diff --check`: passed. Parent corrected a pandas indexing
  expression in a cache test after full mypy caught an overload ambiguity.
- Original triangle reproduction now emits one approximation warning and one
  box `(12.0, 10.25, 90.75, 80.0)` with zero rotation.

## Independent review

Fresh read-only code review returned **ship**, with no actionable findings.
It inspected all source/test/doc changes, feature contracts and ownership;
`git diff --check` passed independently. Parent test/static results were reviewed,
not rerun. The reviewer correctly noted that fake SDK/CVAT/S3 tests alone do not
establish a live result; release gates remain required.

Delegation used native bounded agents with requested GPT-6.1 Sol/medium for
requirements, extraction and cache work, and high effort for the fresh final
review. Runtime model settings were not exposed by the tools. Write ownership
was disjoint; all implementation changes were inspected and verified by parent.

## Mutation triage

The initial full run evaluated 7,495 mutants: 7,278 killed, 217 survived, no
uncovered/unchecked/timeouts. Of those, 207 already had reviewed justifications.
The 10 new survivors were inspected with `uv run mutmut show`: each adds `XX`
around or uppercases one of the five polygon validation reasons. They leave
rejection, task/annotation identity, intelligible reason and skip summary intact.
Exact entries were added under `tool.cveta2.mutation.equivalent`; mutation scope,
profiles and tests were not weakened. A fresh independent reviewer compared the
ten generated mutant functions by AST and confirmed only the stated message
changes. Verdict: ship contingent on the completed full rerun. The rerun passed:
7,495 evaluated, 7,278 killed, 217 justified equivalents, zero unexplained,
uncovered, unchecked or timed-out mutants.

## Release gates and delivery

The task-scoped feature commit `41c045e` passed all configured commit hooks:
Ruff format/check, import-linter, mypy, vulture, pytest with coverage, fast
mutation, build, lockfile and Conventional Commit validation. The feature merged
into main as `5082db8`. Semantic-release generated version **0.8.0**, release
commit `12a9545` and annotated Git tag **v0.8.0**; its release commit hooks passed.
Only the project version changed in the dependency lockfile.

The gated push passed full mutation, version drift and live integration:
**38 passed**, with 160 third-party deprecation warnings. The live suite covers
the existing CVAT/MinIO/ClearML workflows; polygon-specific geometry/cache edge
cases use controlled SDK responses and fake CVAT/S3 ports as described above.

Owned integration tag: `cveta2-codex-20261012-polygon-release-ke05`.
The gate removed its CVAT project and cloud storage, MinIO bucket and ClearML
objects. Independent exact-tag listings afterward showed zero projects/tasks/
storages on CVAT, zero buckets on MinIO and zero projects/tasks on ClearML.
No unrelated stand or durable run was changed.

Remote readback confirmed main at `12a954573b2ce04de1b0c113e8c7ba777bac1232`
and annotated tag `v0.8.0` resolving to that same release commit. No GitHub Release,
package publication or release assets were created. This follow-up documentation
records already observed results after the release push.

## Convergence

The current implementation satisfies all 7 functional requirements, 4 success
criteria and 8 story acceptance scenarios. Reviewed the geometry, validation,
shared mapping, warning, cache-generation and unchanged-interface decisions,
all 5 constitution principles and all 14 tasks against the actual source and
verification evidence. No missing, partial, contradictory or unrequested product
work remains, and no convergence tasks need to be appended.

All checklists remain approved. The original checkout and its unrelated untracked
work were preserved; implementation and release work used an isolated checkout.

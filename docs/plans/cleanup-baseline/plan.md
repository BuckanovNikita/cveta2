# Cleanup and specification baseline

Date: 2026-10-21. Approved route: native behavior-preserving maintenance.
Starting commit: `f6717f0211169f8f94c78da2bfa8dee86bfab602` (v0.11.0 delivery).

## Contract

Consolidate historical specifications, completed maintenance records and the
untracked October bug review into recoverable Git history. Maintain one current
specification at `specs/baseline.md`; retain Spec Kit and current human guides,
governance, tests and release history. The next feature number is 001.
Refactor upload/client transformations, upload orchestration, CVAT transport,
incoming API and CLI parser ownership without changing public behavior.

Preserve public signatures and exported type identities, configuration precedence,
CSV/metadata/recovery formats, error and warning behavior, optional ClearML,
prompt-free API calls and caller-owned resources. Python remains >=3.12,<3.14,
with uv, Hatchling, Ruff, strict mypy, pytest and the existing lockfile. No dependency
updates, workflow-tool changes, blanket test removal or mutation-scope reduction.
Behavior changes require a separate specification and are outside this maintenance.

The original checkout has two unrelated untracked skill links; preserve them.
The 129 untracked bug-review files are explicitly in the approved archive scope.
The companion usage-skill repository has unrelated changes; edit/stage only the
cveta2 contract link and its task evidence. Never install skills as a side effect.

## Architecture and ownership

[architecture.json](architecture.json) records module impact, interfaces, effect
ownership and executable contracts. Validate its planning phase before changes and
its acceptance phase after final diff/check/review reconciliation. Existing inward
layers, SDK ownership, adapter independence, facade exclusion, sibling acyclicity
and inner effect restrictions remain enforced, including negative fixtures.

The parent owns archive/checkpoint, baseline/governance, shared configuration,
mutation mappings, integration, final review and release. After the documentation
cutover, independent bounded workers own (A) upload/domain/client transformations,
(B) CVAT transport and (C) incoming API/CLI, with tests disjoint where possible.
API and CLI changes are sequential within stream C. Shared files and cross-stream
test adjustments return to the parent. No worker commits or delegates further.

## Candidate ledger

| Candidate | Evidence and contrary evidence | Decision and preserved contract | Acceptance |
|---|---|---|---|
| Upload row selection and bbox columns | Client write, resume verification and domain validation duplicate selection; validation and resume intentionally fail differently | simplify: one pure selector/column owner, retaining timing, row/index order and diagnostics | upload helpers, label validation, service/client tests |
| Client transformations | Assembly combines fetch records, frame lookup and upload DTOs; session needs only lookup | simplify: existing mapping owns frame lookup; pure upload mapping owns shape/issue construction; retain matching tolerance and fallback | client, issues, extractors, polygon and recovery tests |
| Upload use case | Staging, recovery and orchestration share one 833-line module; recovery order is deliberate | simplify: package with types, planning, staging, recovery and orchestrator; preserve import entry and every checkpoint/fingerprint | upload/manifest and architecture regression suites |
| CVAT retry/timeout | Connection imports endpoint-adapter internals; 23 repeated decorator stacks have three distinct safety policies | simplify: CVAT-local transport and three explicit composite decorators; preserve order and ambiguous-write refusal | retry policy, timeout, SDK and lifecycle tests |
| Incoming API | One implementation and test module span several capabilities; public exports and model identity are supported | simplify: capability modules and aligned tests; retain signatures, serialization, connection ownership and precedence | API, org resolution, sync root and facade identity tests |
| CLI parsing | Command configuration dominates cli.py; registry is already declarative and intentionally late-bound | simplify: configuration beside command families, shared parser helpers, retained dispatch/error boundary | parser/help and affected command tests |
| Facades, count_task_shapes and compatibility parameters | Few checkout callers do not establish absence of public consumers | retain code/signatures; correct stale descriptions | public imports, identity and task tests |
| Legacy/strict CSV readers and publication rechecks | Literal positional diagnostics and parent races make superficially duplicate operations different | retain policies, cache fallbacks and invocation-time settings | dataset, verification, bundle and policy tests |
| Historical feature/audit prose | All 134 feature tasks are checked; later delivery closes earlier pending notes | archive after complete checkpoint; preserve current contract, dispositions and evidence limits | manifest/hash recovery, source crosswalk and links |

## Checkpoint and cutover

Checkpoint all 107 old specs files and three old maintenance files at their native
Git paths. Capture the 129-file bugs tree in `archive/legacy-bugs.tar.gz` with a
manifest of original paths, archive members/native Git paths, sizes, modes and
SHA-256. Preserve the old SHA256SUMS unchanged and record its 13 current mismatches;
do not claim the current proof scripts equal the original capture. Inspect selected
content for credentials before staging. Historical proof scripts are evidence,
not current acceptance tests (their successful exit often demonstrated a bug).

Use ordinary commits and hooks. The archive container avoids changing proof bytes
or lint rules: raw historical scripts currently fail Ruff and duplicate-module
mypy checks. Verify checkpoint objects and full SHA before deletion. Keep original
implementation SHAs distinct from the archival commit. Include an immutable source
table and both Git-file/archive-member recovery commands in the baseline.

Draft and validate reference replacements across all retained documents before
applying them, including repeated links and anchors. Absorb the dataset contract;
update sdist contents, documentation tests, entry-point guidance and the portable
usage link. Retain current guides and installed workflow tools. Remove only the
manifest's retired paths, and clear the retired active-feature pointer. Confirm
next-feature dry run returns 001 without modifying tooling or branches.

## Acceptance

Use `uv run` for Python tools. Focused behavioral tests precede integrated Ruff,
mypy, Vulture, lint-imports, effect checks, architecture tests and the full suite
with configured coverage. Preserve tests.env_isolation and fixture teardown.
Migrate mutation paths/equivalence evidence with moved functions; fast and full
gates must have zero unexplained survivors and zero stale justifications.
Run live upload/fetch/recovery coverage through the integration skill, with an
owned run tag, serial execution and exact-tag cleanup. Validate built wheel/sdist
imports, CLI entry point, optional dependency boundary and package data outside
the checkout on supported interpreters.

Documentation checks cover maintained links/anchors, baseline capability coverage,
archive retrieval/hashes, sdist inventory and numbering. Dated evidence records
actual results and unavailable checks. Fresh independent review follows parent
integration and verification, covering behavior, architecture and provenance.
Reconcile the entire task-owned diff before architecture acceptance.

Complete task-scoped Conventional Commits, merge into main, evaluate the existing
semantic-release workflow and push commits/any resulting Git tag after configured
gates. Never publish GitHub Release objects or packages. See [tasks.md](tasks.md)
for status; this plan records intent, not completed acceptance.

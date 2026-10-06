# Dataset correctness evidence — 2026-10-04

## Workflow and scope

Executed installed specify, clarify, plan, checklist, tasks, read-only analyze, implement and converge stages with explicit `SPECIFY_FEATURE_DIRECTORY=specs/003-dataset-correctness`. No shared feature selection writes, commits, dependency changes or shared stand operations. Requirements checklists passed before implementation. Analysis: nine functional requirements, nine covered, no critical/high findings, no unresolved ambiguity. Parent owns living contracts, documentation validation, consolidated gates and fresh independent review.

## Baseline and per-finding results

Baseline revision `875dca9b5cfc5bb48218257624defe3c18bc4f6e`. Parent ran all 25 historical Python reproducers against the isolated baseline: every script exited zero, establishing the originally asserted defective observations. Parent baseline full suite: 1777 passed, coverage 92.07%. The first local dataset regression run before behavior edits additionally produced 39 failures and four passes across 43 cases. Symlink refresh and missing-split rejection were already working; these are compatibility checks, not new fixes.

| ID | Failing observation and boundary | Implemented acceptance and verification |
| --- | --- | --- |
| DATA-001 | Deleted-name CSV reader coerced NA/N/A/NULL to null and 001 to integer; all four new reader tests failed before fix. | Shared literal-text CSV contract is reused; deletion rows and legacy plain names remain supported. Existing merge suites plus four direct literal-name regressions pass. |
| DATA-002 | Unsupported mixed splits produced output (including traversal-like split); six new invalid-split cases failed while two missing-split cases already passed. | All exportable row splits must be train/val/test before output creation. Eight missing/unsupported mixed-split tests pass for YOLO and COCO. |
| DATA-003 | Copy/hardlink/auto/reflink reruns retained old destination bytes after replacement of the source; eight new cases failed, two symlink cases already passed. | Replace destinations with current resolved image data/link semantics, preserving same-file hardlinks safely. Ten two-export tests cover both exporters and all five modes. |
| DATA-004 | COCO removed rows/splits retained stale files; unsafe ownership metadata and invalid dimensions were not rejected before writes. | Prior split annotation JSON establishes ownership. Preflight rejects corrupt/duplicate/unsafe inventories, symlink parents, unowned destination collisions and reserved metadata filenames. Only owned obsolete files/empty owned splits are removed; unrelated files and empty unowned directories remain. Replacement, no-write invalid-input, unsafe-path and corrupted-metadata regressions pass. |
| DATA-005 | Unterminated quoted CSV escaped as ParserError. | Expected parser/decode/I/O failures become contextual Cveta2Error; unexpected RuntimeError still propagates. Buffered NUL-byte preflight prevents pandas silently truncating image names. Parse, internal-failure and NUL input regressions pass. |
| DATA-006 | Malformed dataset/names YAML leaked parser errors; malformed ID/name maps leaked ValueError or silently coerced invalid data. | Specific YAML/decode/I/O exceptions and invalid external types/maps produce contextual Cveta2Error; unexpected internal RuntimeError propagates. Both YAML input modes, malformed class mappings, and unexpected failures are tested. |
| DATA-007 | Fractional classes truncated, nonfinite coordinates/confidence and out-of-domain values entered parsed boxes. | Nonnegative integral finite class IDs; centers [0,1], sizes (0,1], confidence [0,1]. Invalid lines emit file:line warning and skipped summary while valid siblings survive. Eight malformed numeric cases and exact line-number regression pass. |
| OPS-001 | Historical baseline cloned first-task images into every task and crashed for an empty project. | Each task downloads its own metadata frame sequence and uploads to task-specific keys. Attach data with predefined sorting and explicit upload_file_order so source frame indices stay aligned. Fake main-path tests prove differing counts/order and bytes, deleted-frame call compatibility and empty-project safety. Parent owns live stand validation. |
| OPS-002 | Historical baseline treated source class IDs as positions, silently dropping sparse IDs/reassigning negative indices. | Preserve ID-name keyed mapping through CVAT name lookup, reject malformed mappings/IDs and unknown IDs before opening remote client. Fake helper main-path test retains sparse IDs 2/5 as cat/dog; unknown and invalid class ID tests prove refusal. |

Sibling CVAT-001 helper boundary: duplicate scoped source-project names now reject with candidate IDs before cloud/project mutation; dedicated regression passes.

## Accepted compatibility and bounded changes

Image basename/stem uniqueness remains an input contract. Missing local images still warn and retain metadata/labels. YOLO extra numeric fields remain accepted and reported as detection-prefix compatibility; every parsed numeric value must be finite. Unknown service-import classes retain existing class_N fallback when no complete mapping is supplied; strict unknown-ID refusal belongs to the upload helper. Class-name YAML values must now be nonempty unique strings; prior scalar/non-string coercion tests were updated to the explicit malformed-input requirement. SDK imports in helper dev tools are pre-existing and unchanged; package imports remain inside the established SDK boundary. No new future-annotation imports were introduced.

Export preflight validates image names, required dimensions, box labels and finite ordered coordinates before destination changes. COCO cleanup never removes an arbitrary tree. File symlinks recorded as owned images can be refreshed/unlinked without following their targets; directory/metadata symlinks cannot authorize cleanup. Unexpected I/O failures after successful preflight are not transactional rollback guarantees.

## Checks actually run

- `uv run --no-sync pytest tests/test_convert_common.py tests/test_convert_yolo.py tests/test_convert_coco.py tests/test_output.py tests/test_merge.py tests/test_review_dataset.py -q -n 0`: **278 passed**, including **63** new regressions.
- Ruff checks on changed conversion/output/merge services, both helper scripts and changed/new test files: **passed**.
- `uv run --no-sync mypy cveta2/services/convert cveta2/services/output.py cveta2/services/merge.py`: **passed**, six source files.
- Broader mypy was attempted after test helper imports were changed to importlib, avoiding duplicate script module identities; remaining errors at that time belonged to parallel interface/CVAT tests and were reported to parent, not described as passing.
- New helper tests explicitly skip only if scripts are absent from mutation copied trees; service regressions remain active. Imports use isolated module names rather than introducing a scripts package.

## Documentation and remaining gates

Parent must reconcile the living dataset reference and Russian user documentation for COCO replacement ownership/refusal, image refresh, supported splits, expected parse errors/NUL CSV refusal, strict names mappings, numeric domains and file:line warnings. Helper guidance must describe task-specific image data and sparse source IDs. Parent consolidated static/full/mutation checks, actual integration outcomes and independent review remain pending; targeted mocked checks do not prove live CVAT/S3 publication.

## Mutation-driven verification follow-up — 2026-10-04

After the parent clean full mutation run, inspected exact surviving/timed-out mutants with read-only `mutmut results/show`, then strengthened semantic regressions without changing production behavior or the mutation configuration. Added numeric endpoint acceptance, finite-domain rejection, duplicate/whitespace names, invalid flat-name maps/root types, contextual deletion/CSV errors, missing export schema fields, image names, all dimensions, box coordinates/labels, split diagnostics and unknown modes. Added retained val/test reruns, removed test-only ownership, unowned file/dangling-symlink collision, destination/metadata symlink and file refusal, malformed ownership entries, missing owned image cleanup and contextual metadata diagnostics.

The CSV EOF test uses a task-owned binary stream that emits EOF once and fails immediately if read again. This observes finite reader termination without a hanging mutant process or an assertion about implementation chunk size. Timed-out sentinel mutants are not proposed as equivalents. NUL fixtures are built by replacing valid CSV bytes rather than relying on pandas versions to serialize invalid NUL cells.

Checks: **406 affected tests passed**, including **191** review-dataset cases; Ruff and mypy for the changed regression test passed. No mutation rerun was performed by this delegate; parent owns the next measured mutation verdict. Exact equivalent proofs and six stale entry removals were sent to the parent as temporary review artifacts; no pyproject.toml edits were made. Equivalences cover only redundant conditions, tuple iteration identity, existing parent directories, unreachable diagnostic branches, falsy parse state, chunk sizing and presentation-only allowed-split sentences. Actionable lost source/value context is tested rather than allowlisted.

## EOF mutation-order diagnosis — 2026-10-04

Round-three semantic dataset survivors were resolved, but CSV wrong-sentinel mutants 11/17 still timed out. Inspected installed mutmut: caller associations are sets, converted directly to an unsorted pytest argument list. The stats include the bounded EOF regression among 266 reader callers, so stale association was not the cause: an ordinary real-file caller could hang before the bounded test ran. Ordinary collection with a real-reader node specified first reproduced that ordering.

Parent added stable pytest collection priority for the finite-EOF regression, preserving all other items and their order without a mutation-environment condition. Added a subprocess collection proof that deliberately selects the real reader first, then the bounded EOF regression; collection returns both nodes with the bounded regression first. The proof uses the current interpreter, fixed node IDs and the existing isolation plugin, requires no extra runtime dependency, and runs collection only. The stream regression still observes actual finite EOF behavior and raises immediately on a repeated EOF read.

Checks: **407 affected cases passed**, including **192** review-dataset cases; both EOF guard tests passed independently. Ruff and mypy for the modified regression file passed. No production changes or mutation runs by this delegate; the parent must verify both former timeout verdicts in the next measured gate.

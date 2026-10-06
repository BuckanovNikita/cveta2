# Remediation ledger — 2026-10-04

Scope: 26 findings at baseline `875dca9`: 22 confirmed defects, three clarified contracts, one conditional retry risk. The original audit remains local; this ledger and committed regression fixtures are self-contained.

## Baseline and reproduction boundary

All 25 historical Python reproducers were run in an unchanged detached baseline checkout, under isolated configuration and caches, as a non-root user. Every script exited 0, meaning it observed the historical symptom. OPS-003 used the actual shell wrapper and profile resolver with a mutation sentinel: the unknown profile incorrectly reached mutation execution. No historical reproducer exit is treated as a fixed-behavior pass.

Baseline full pytest: **1,777 passed**, branch-aware coverage **92.07%** against the required 90% gate. The CVAT-005 post-write 503 was injected at a fake client boundary; it was not observed naturally on a live stand.

## Existing changes included in the PR

The nine commits from `origin/main` through `875dca9` are pre-existing work: shared infrastructure migration (`3037a2a`, `705586b`, `a9b7c56`, `141322e`, `1717184`, merge `b027800`, and cleanup `1a77d1f`), release `b70ac47` (0.6.0), and Spec Kit adoption `875dca9`. Remediation follows that baseline; no version or changelog change is part of these fixes.

## Findings

### CVAT-001 — Duplicate task and project names resolve to arbitrary targets

- Original classification: **confirmed-defect**. Observation: Duplicate task and project names resolve to arbitrary targets.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [CVAT-001 requirement](../../002-cvat-write-safety/spec.md).
- Implementation and regression: Scoped name selection rejects duplicates with matching IDs and refreshes active-client project names; numeric selectors remain supported. [Regression tests](../../../tests/test_review_cvat.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Duplicate names now require explicit IDs.

### CVAT-002 — Incomplete labeled boxes are silently omitted during upload

- Original classification: **confirmed-defect**. Observation: Incomplete labeled boxes are silently omitted during upload.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [CVAT-002 requirement](../../002-cvat-write-safety/spec.md).
- Implementation and regression: Finite complete labelled boxes are validated before CVAT writes; empty/deleted records remain valid. [Regression tests](../../../tests/test_review_cvat.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Malformed annotations now fail instead of disappearing.

### CVAT-003 — Resume identity ignores annotation content

- Original classification: **confirmed-defect**. Observation: Resume identity ignores annotation content.
- Historical boundary: Component-reproduced; end-to-end resume flow statically validated. Baseline reproduced as described above.
- Accepted behavior and compatibility: [CVAT-003 requirement](../../002-cvat-write-safety/spec.md).
- Implementation and regression: Schema 3 binds normalized annotation/options intent and frozen frame mapping; resume verifies exact shape multisets and frame identity. Critical checkpoints are required before create/attach. [Regression tests](../../../tests/test_review_cvat.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Legacy manifests cannot authorize resume; partial/conflicting or uncertain remote state requires manual reconciliation. Basename-only server metadata can verify unique basenames only, with a warning.

### CVAT-004 — Manifest cleanup failure escapes after remote upload succeeds

- Original classification: **confirmed-defect**. Observation: Manifest cleanup failure escapes after remote upload succeeds.
- Historical boundary: Component-reproduced; post-upload call path statically validated. Baseline reproduced as described above.
- Accepted behavior and compatibility: [CVAT-004 requirement](../../002-cvat-write-safety/spec.md).
- Implementation and regression: Completed counts persist before cleanup; unlink denial warns with task/path, and retained completion state prevents repeat writes. [Regression tests](../../../tests/test_review_cvat.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Permission failure is exercised locally; no shared filesystem permissions changed.

### CVAT-005 — `503 Retry-After` replays non-idempotent CVAT writes

- Original classification: **conditional-risk**. Observation: `503 Retry-After` replays non-idempotent CVAT writes.
- Historical boundary: Reproduced with an ambiguous-write fake; no live CVAT write was performed. Baseline reproduced as described above.
- Accepted behavior and compatibility: [CVAT-005 requirement](../../002-cvat-write-safety/spec.md).
- Implementation and regression: Non-idempotent create/append no longer replay ambiguous 503 responses; read and separately justified idempotent retries remain. [Regression tests](../../../tests/test_review_cvat.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Original ambiguity was simulated. The live regression deliberately injects a post-write client failure; no natural outage is claimed.

### DATA-001 — merge ignores deletions whose image name is a pandas NA token

- Original classification: **confirmed-defect**. Observation: merge ignores deletions whose image name is a pandas NA token.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [DATA-001 requirement](../../003-dataset-correctness/spec.md).
- Implementation and regression: Deletion CSV uses literal-string reader options, preserving NA-like names. [Regression tests](../../../tests/test_review_dataset.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: No intentional compatibility break.

### DATA-002 — export accepts unsupported split values and writes an unreferenced YOLO tree

- Original classification: **confirmed-defect**. Observation: export accepts unsupported split values and writes an unreferenced YOLO tree.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [DATA-002 requirement](../../003-dataset-correctness/spec.md).
- Implementation and regression: All exportable rows require train/val/test before destination changes; errors identify offending rows/images. [Regression tests](../../../tests/test_review_dataset.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Missing or unsupported splits are rejected.

### DATA-003 — repeat export silently keeps stale image bytes

- Original classification: **confirmed-defect**. Observation: repeat export silently keeps stale image bytes.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [DATA-003 requirement](../../003-dataset-correctness/spec.md).
- Implementation and regression: Repeated export replaces stale destination bytes in supported link/copy modes. [Regression tests](../../../tests/test_review_dataset.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Existing same-file hardlinks remain valid.

### DATA-004 — repeat COCO export retains removed splits and images

- Original classification: **unclear-contract**. Observation: repeat COCO export retains removed splits and images.
- Historical boundary: Unclear contract; stale-output observation reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [DATA-004 requirement](../../003-dataset-correctness/spec.md).
- Implementation and regression: COCO export preflights prior metadata ownership and replaces owned images/annotations/splits while preserving unrelated files. [Regression tests](../../../tests/test_review_dataset.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Replacement is the clarified contract; unsafe/ambiguous ownership is rejected before mutation.

### DATA-005 — malformed dataset CSV escapes the service error boundary

- Original classification: **confirmed-defect**. Observation: malformed dataset CSV escapes the service error boundary.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [DATA-005 requirement](../../003-dataset-correctness/spec.md).
- Implementation and regression: Expected CSV parser/encoding/NUL failures become contextual domain errors; unexpected internal failures propagate. [Regression tests](../../../tests/test_review_dataset.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Malformed inputs now produce Cveta2Error.

### DATA-006 — malformed YOLO YAML escapes the conversion error boundary

- Original classification: **confirmed-defect**. Observation: malformed YOLO YAML escapes the conversion error boundary.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [DATA-006 requirement](../../003-dataset-correctness/spec.md).
- Implementation and regression: Expected YAML syntax/type/mapping failures become contextual domain errors. [Regression tests](../../../tests/test_review_dataset.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Unexpected implementation failures remain diagnosable.

### DATA-007 — YOLO import accepts non-integral classes and non-finite coordinates

- Original classification: **confirmed-defect**. Observation: YOLO import accepts non-integral classes and non-finite coordinates.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [DATA-007 requirement](../../003-dataset-correctness/spec.md).
- Implementation and regression: YOLO rows enforce integral nonnegative class IDs, finite numeric domains and file/line warnings; valid siblings survive. [Regression tests](../../../tests/test_review_dataset.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Invalid lines are skipped with warnings; centers [0,1], sizes (0,1], confidence [0,1].

### OPS-001 — Cloning substitutes the first task's images into every task

- Original classification: **confirmed-defect**. Observation: Cloning substitutes the first task's images into every task.
- Historical boundary: Reproduced at the orchestration boundary with a deterministic fake; no live cloning performed. Baseline reproduced as described above.
- Accepted behavior and compatibility: [OPS-001 requirement](../../003-dataset-correctness/spec.md).
- Implementation and regression: Clone reads each task’s own frames, stores task-specific objects, and explicitly preserves upload order; empty projects are safe. [Regression tests](../../../tests/test_review_dataset.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Live byte/frame correspondence is separately tested by test_review_remediation.py.

### OPS-002 — The dataset upload helper silently misassigns or drops class IDs

- Original classification: **confirmed-defect**. Observation: The dataset upload helper silently misassigns or drops class IDs.
- Historical boundary: Reproduced through actual main() with real YAML, YOLO and image inputs and fake remote services; no live CVAT mutation performed. Baseline reproduced as described above.
- Accepted behavior and compatibility: [OPS-002 requirement](../../003-dataset-correctness/spec.md).
- Implementation and regression: Upload helper preserves sparse source ID/name mappings and rejects malformed maps/unknown IDs before remote creation. [Regression tests](../../../tests/test_review_dataset.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Unknown IDs no longer silently disappear or change class.

### OPS-003 — An invalid mutation profile prints an error but exits successfully

- Original classification: **confirmed-defect**. Observation: An invalid mutation profile prints an error but exits successfully.
- Historical boundary: Reproduced with the actual configured full-scope mutation gate in a disposable checkout. Baseline reproduced as described above.
- Accepted behavior and compatibility: [OPS-003 requirement](../spec.md).
- Implementation and regression: Shell wrapper captures profile resolver status before scope synchronization or mutation execution. [Regression tests](../../../tests/test_mutation_wrapper.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Unknown and explicitly empty profiles exit nonzero; valid fast/full profiles reach the engine.

### STOR-001 — S3 upload errors escape the transfer failure accounting

- Original classification: **confirmed-defect**. Observation: S3 upload errors escape the transfer failure accounting.
- Historical boundary: Reproduced with the installed boto3 client and botocore Stubber. Baseline reproduced as described above.
- Accepted behavior and compatibility: [STOR-001 requirement](../spec.md).
- Implementation and regression: Transfer accounting catches real boto3 S3UploadFailedError wrappers and lets independent transfers finish. [Regression tests](../../../tests/test_review_storage.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Permanent authorization errors are not indiscriminately retried; Stubber exercises real boto3 wrapping.

### STOR-002 — An invalid read-only cache aborts fetch

- Original classification: **confirmed-defect**. Observation: An invalid read-only cache aborts fetch.
- Historical boundary: Reproduced using real filesystem permissions as a non-root user. Baseline reproduced as described above.
- Accepted behavior and compatibility: [STOR-002 requirement](../spec.md).
- Implementation and regression: Unreadable/invalid cache and failed invalidation warn and return a miss. [Regression tests](../../../tests/test_review_storage.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Real non-root read-only permissions verified; uncached path remains supported.

### STOR-003 — S3 sync collapses distinct leading-separator keys into one file

- Original classification: **unclear-contract**. Observation: S3 sync collapses distinct leading-separator keys into one file.
- Historical boundary: Unclear contract; normalization collision reproduced outside the guaranteed unique-basename input domain. Baseline reproduced as described above.
- Accepted behavior and compatibility: [STOR-003 requirement](../spec.md).
- Implementation and regression: Complete canonical S3 destination mapping, symlink aliases and ancestor collisions are checked before writes. [Regression tests](../../../tests/test_review_storage.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Noncanonical or colliding keys now reject the whole sync before writes.

### STOR-004 — Image download treats a directory as a cached image

- Original classification: **confirmed-defect**. Observation: Image download treats a directory as a cached image.
- Historical boundary: Reproduced using an existing directory. Baseline reproduced as described above.
- Accepted behavior and compatibility: [STOR-004 requirement](../spec.md).
- Implementation and regression: Only files count as cached; directory destinations count as failures and remain intact. [Regression tests](../../../tests/test_review_storage.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Existing files are treated as complete without decoding image content.

### UI-001 — A project named `..` escapes `cache.images_root`

- Original classification: **confirmed-defect**. Observation: A project named `..` escapes `cache.images_root`.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [UI-001 requirement](../spec.md).
- Implementation and regression: Reserved/separator project components are encoded and resolved containment is enforced. [Regression tests](../../../tests/test_review_storage.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Logical names remain unchanged; affected default cache paths use encoded components.

### UI-002 — Typed configuration errors bypass the CLI error boundary

- Original classification: **confirmed-defect**. Observation: Typed configuration errors bypass the CLI error boundary.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [UI-002 requirement](../spec.md).
- Implementation and regression: CLI catches typed validation errors and reports field diagnostics without input values or incidental traceback. [Regression tests](../../../tests/test_review_interfaces.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: API retains typed exceptions.

### UI-003 — Negative data timeouts are accepted and fail inside HTTP setup

- Original classification: **confirmed-defect**. Observation: Negative data timeouts are accepted and fail inside HTTP setup.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [UI-003 requirement](../spec.md).
- Implementation and regression: Configuration rejects negative/nonfinite data timeouts; None/zero/positive semantics remain. [Regression tests](../../../tests/test_review_interfaces.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Invalid values fail at configuration validation.

### UI-004 — `setup-clearml` can discard the chosen enabled state

- Original classification: **confirmed-defect**. Observation: `setup-clearml` can discard the chosen enabled state.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [UI-004 requirement](../spec.md).
- Implementation and regression: ClearML enabled-only changes are persisted even with unchanged mapping values. [Regression tests](../../../tests/test_review_interfaces.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Wizard inputs are simulated; saved config is reloaded.

### UI-005 — Noninteractive removal cannot delete a stale ignore entry

- Original classification: **confirmed-defect**. Observation: Noninteractive removal cannot delete a stale ignore entry.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [UI-005 requirement](../spec.md).
- Implementation and regression: CLI and API remove stored numeric IDs without listing remote tasks; names/unknown IDs still resolve remotely. [Regression tests](../../../tests/test_review_interfaces.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: API regressions also in test_api.py; project resolution remains required.

### UI-006 — Missing-credential errors name the ambient config instead of `Connection.config_path`

- Original classification: **confirmed-defect**. Observation: Missing-credential errors name the ambient config instead of `Connection.config_path`.
- Historical boundary: Reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [UI-006 requirement](../spec.md).
- Implementation and regression: Selected config path travels with CvatConfig to credential diagnostics. [Regression tests](../../../tests/test_review_interfaces.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: Selected profile is reported without exposing credential values.

### UI-007 — Doctor's exit status does not express the health-check result

- Original classification: **unclear-contract**. Observation: Doctor's exit status does not express the health-check result.
- Historical boundary: Unclear contract; end-to-end CLI observation reproduced. Baseline reproduced as described above.
- Accepted behavior and compatibility: [UI-007 requirement](../spec.md).
- Implementation and regression: Doctor required CVAT configuration failures/unavailability exit 1; optional AWS/image-cache/cache warnings exit 0; disabled cache is explicit. [Regression tests](../../../tests/test_review_interfaces.py).
- Documentation: shared user guidance and the linked feature contract describe this behavior. [Integrated verification](verification-2026-10-04.md) records full-suite, runtime, mutation and live evidence; feature evidence records focused checks.
- Compatibility and limitations: This is a configuration diagnostic contract, not a live CVAT network-health guarantee.

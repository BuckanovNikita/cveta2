# cveta2: functionality

Fetch, curate, convert and publish reproducible datasets from CVAT and S3 through a
Russian CLI and a prompt-free Python API. Preserve original source evidence, make
repairs explicit and reject ambiguous remote changes before mutation.
[Terms](../GLOSSARY.md) distinguish standalone and managed preparation.

This specification owns functional behavior. The [dataset and public interface
reference](../docs/dataset-contract.md) supplies exact CSV columns, API return values,
serialized reports and metadata schemas. The [API](../docs/python-api.md),
[CLI](../docs/cli.md) and [configuration](../docs/configuration.md) guides supply
call signatures, command options and configuration fields. Internal organization
may change while these public behaviors and formats remain compatible.

## Connections, configuration and failures

Users select CVAT projects by ID or organization-scoped name. Ambiguous names report
matching IDs before mutation; an empty organization selects the personal workspace.
Explicit connection values override environment, selected file and bundled defaults.
Invalid selected configuration fails without fallback. API calls never prompt or exit;
owned sessions close deterministically and injected clients remain caller-owned.
ClearML is optional, and ordinary CSV verification needs neither CVAT nor ClearML.

Expected operational failures have typed errors and actionable CLI messages. Preserve
unexpected defects. Diagnostics identify the failing resource, time, HTTP status and
sanitized context without credentials, raw HTML or YAML values; concurrent requests
cannot mix diagnostic context. Missing diagnostic values are explicit. Timeout zero
or unset means no read timeout; positive values use the requested read timeout and a
ten-second connect timeout. Negative/nonfinite values fail.

Retry transient reads within configured budgets. Non-idempotent create/append retries
only refused 429 responses, never ambiguous 503 responses; idempotent operations use
their declared retry policy. Invalid Retry-After values use ordinary backoff. Exhausted
429 aborts fetch; ordinary per-task 5xx failures identify skipped tasks and continue
unless fail-on-error is selected. Authentication, configuration and exhausted connection
failures abort. Optional issue-read failures produce degraded output, not complete cache
entries. Report cached/fetched/skipped/degraded totals and distinguish wall time from
summed worker time. Configuration diagnosis succeeds only when required checks succeed;
optional warnings do not imply live CVAT health or cause failure.

## Fetch and partition

Fetch full projects or individual tasks with annotations, images, task/job/frame
identity, paths, attributes and frame issues. Full fetch emits dataset, obsolete,
in-progress and deleted partitions. Preserve literal labels such as `NA` and `001`,
Unicode, empty images and explicit deletion rows. Fetch leaves split assignment unset;
CVAT subset is independent. Image basenames and stems must be unique across distinct
images in a dataset; repeated evidence for the same image is allowed.

Determine task completion from all live jobs. Explicit completion wins over legacy
stage/state fallback; missing/null legacy state is unfinished, and unfinished evidence
wins conflicting finished evidence. Row stage/state comes from its owning regular job;
ground-truth/replica jobs do not overwrite it. Among overlapping regular jobs prefer
unfinished positions, then lowest job ID. For an image, highest task ID wins and
deletion wins a same-task tie. Task update timestamps invalidate caches but never
choose annotation recency. `whats-new` compares completed membership across dataset,
obsolete and deleted files; unfinished evidence keeps a task eligible.

Retain rectangles and their rotation. Convert standalone polygons to tight axis-aligned
boxes over all vertices, with zero rotation, preserving provenance and issuing an
approximation warning. Invalid polygon geometry skips contextually; all-rejected frames
remain empty images. Tracks and other shapes are unsupported and warn. Frame issues
repeat on all frame rows, retaining comment order and issue/state correspondence.

Reuse task evidence only when identity, completion and live revision match. Invalid
ordinary cache entries warn and refetch even if cache repair fails. Force refresh bypasses
reads; disabled caching avoids ordinary local/S3 cache use. Full-fetch pruning uses one
complete unfiltered task inventory after promotion; later deletions reconcile next run.
Per-task debug CSVs are explicit, not an automatic fetch side effect.

Canonical S3 keys preserve frame subdirectories. Cached canonical files need no S3
request. Up to 2,000 uncached images use direct GET; larger batches list first. Only
missing-key responses allow basename fallback; alternate-key discovery repeats before
reusing its cached bytes. Bound transfer memory, retry interrupted transfers and publish
files atomically. Validate the complete destination mapping before writes; symlink,
ancestor and key collisions fail without modifying the destination. Sync only downloads
missing objects and never changes remote objects.

## Explicit CVAT changes and recoverable upload

Only opt-in full-project fetch promotes eligible annotation/completed jobs to
acceptance/completed. Every job in a nonignored task must already be annotation/completed
or acceptance/completed; empty, mixed and ignored tasks are untouched. Invalidate local
and enabled S3 task cache before any write, even with ordinary cache disabled. Read,
invalidation or update failure aborts before annotation retrieval or output. Successful
remote updates remain; rerun changes only remaining eligible jobs. External concurrent
edits have no transaction guarantee.

Upload validates complete finite labelled boxes, labels, paths and storage mapping
before remote writes; empty/deletion-only inputs are valid. Persist recoverable intent
before task creation or attachment. Resume requires unchanged content, multiplicity,
frame order, issues, deletions, options and storage mapping. Reconcile known remote tasks
against project, ordered frame identity and exact intended shapes. Partial/conflicting
content blocks append; uncertain creation requires inspection, never duplicate creation.
Failed S3 uploads prevent task creation. Completed success survives local cleanup failure.

Resume adds only missing issues, reuses exact shapes and may repeat idempotent deletion
or completion. Create issues only from new, nonempty issue text with a complete bbox;
identical image/text/bbox rows deduplicate and missing boxes warn/skip. Preserve exported
open/resolved states. Expose explicit label updates, task deletion/status changes,
mark-deleted and drop-label operations. Repeated mark-deleted returns zero without a
write. Removing a stored ignored numeric ID does not require that remote task to exist.

## Conversion and local verification

Merge CSVs and convert YOLO/COCO while preserving literal identities, sparse class
mapping and source lineage. Every exportable row needs train/val/test before destination
mutation. YOLO numeric values must be finite with valid class IDs, normalized geometry
and confidence; malformed lines warn and skip independently. Repeat exports refresh
image bytes. Cleanup removes only prior export-owned files and preserves unrelated
files; uncertain ownership cannot authorize deletion. Unexpected I/O may leave partial
output and must be reported, without a rollback claim.

Verify CSV or caller-owned tables using cveta2 or clearml-yolo profiles. Read CSV
lexically, retain extra fields and original values, and report original row positions.
Malformed headers/record widths and structural failures block; a header-only CSV is
valid. Do not mutate caller data. Validate labels, dimensions, finite boxes, geometry,
image ownership and split rules. Quarantine the entire affected image group. Compare
duplicates deterministically in input order; training conflicts across classes quarantine
the image. Unknown bounds and skipped image checks remain explicitly unverified.

Optional media checks resolve canonical local files, account for EXIF orientation and
never download URI paths. Training box sides and area must exceed two. Propose clipping
only with trustworthy bounds, no other blocking group errors, each overflow strictly
below ten pixels and a still-valid result. Default verification reports only; explicit
cleaning accepts repairs/removals into a new output directory, never overwrites inputs
and cannot erase structural failures. Validity and need for cleanup are distinct outcomes.
Reports retain original broken evidence, reasons and checked/skipped checks.

## Standalone preparation and publication

Standalone preparation consumes the four exact full-fetch CSVs and captures source
bytes before parsing. Split assignment is external: every retained image has one split,
train and val are nonempty and train contains a box. Cleanup cannot supply missing choices.
Reconcile classes by stable registry number, retain aliases and empty-class policy on
rename, and require explicit acceptance of new identities/renames. Unknown or excluded
classes quarantine whole images. Missing decisions are structured API results.

Validate roots and all source-path coverage before filtering, with symlink confinement.
Local and S3 roots are independent, not inferred mirrors. Bundle media inspection is
mandatory: readable local images, supported decoded format and EXIF-aware sides of at
least ten pixels. Included task IDs come from retained source pairs; obsolete tasks need
completed evidence and strictly newer annotation/deletion evidence for every image.
Unfinished or merely filtered tasks are not automatically obsolete.

Prepare into a new directory outside the source. Unresolved findings produce diagnostics
and captured sources but no uploadable payload. A ready bundle binds its destination,
exact parent, decisions, source/payload hashes and completion checksum. The user reviews
it before a separate same-machine upload. Its checksum detects accidental edits, not a
hostile machine owner's rewriting. Standalone preparation uses format version 1.

Publication accepts only the prepared directory. Recheck captured and prepared bytes,
media, roots, class registry and latest finalized nonarchived exact parent before child
creation. A changed/unavailable prerequisite requires new preparation. Parents remain
unchanged; CSV-only parents require a new dataset name. Publish a stable checked copy
containing exactly dataset.csv, dataset.yaml and tasks.yaml; remove inherited child
files/links and confirm finalization. Never publish images or local review diagnostics.
Failure after creation reports the child ID and uncertainty for inspection before retry.
Fetch never initializes or publishes to ClearML, and obsolete automatic-publication
settings cannot enable it. CVAT upload is a separate operation.

## Managed datasets

Managed definitions name CVAT and S3-CSV sources, exact ClearML destination, class/image
policy, overlap decisions and split policy. A definition uses one configured CVAT
server/organization. Source names/references and destination pairs must be unambiguous.
Shared policy owns these choices; personal settings own credentials, local caches and
runtime settings. Personal fields cannot override shared policy. Selected files fail
strictly; shared file selection is explicit argument, environment, then saved reference.

Attach shared configuration without rewriting it or requesting credentials. Migration
previews a redacted field split, preserves unknown values in a private original backup,
and requires explicit approval. Cancellation changes nothing; repeated/interrupted
migration is recoverable. Never invent project IDs, overwrite a differing shared file
or let noninteractive operation approve migration. Policy writes update shared storage
or fail; local-path writes remain personal.

Managed fetch pins the latest finalized nonarchived parent. Reuse unchanged completed
CVAT task evidence only after checking live completion/revision; refresh changed,
new/reopened/deleted tasks and invalidate reuse on label/registry changes. Explicit
refresh bypasses reuse. Capture each S3 CSV's bytes/hash and available object identity
on every fetch; changed objects replace their source contribution. S3 rows never acquire
invented CVAT task IDs. Missing mandatory sources fail assembly. Preserve raw evidence,
including empty tasks and rows discarded by project partitioning, independently of
combined annotations.

Users may run arbitrary external transformations. Managed preparation accepts the
transformed CSV without assuming one-to-one rows; untraceable lineage is unmapped.
Assign train/val/test with default targets 0.6/0.2/0.2 and seed 42, preserving published
assignments by image-content hash and assigning new content deterministically. Identical
content cannot cross splits; report and replace script-supplied splits. Targets do not
promise exact counts. No silent rebalance; changed split policy needs a new lineage.
Require nonempty train/val and viable training boxes.

Overlapping content requires explicit source selection/exclusion tied to participating
source names; changed membership needs renewed resolution. Different content with one
filename blocks. Apply training/image/class checks and explicit cleaning as above.
Report CVAT review issues only for unambiguous original project/task/frame lineage,
using original coordinates when reliable. Deduplicate retries and preserve annotations,
job states and human issues. Mapped delivery failures block publication; unmapped/S3
findings stay local. Feedback metadata alone must not make annotations appear stale.

Managed preparation uses format version 2, binding raw evidence, transformed CSV,
resolved relevant definition, exact parent, media and payloads. Unrelated shared entries
do not invalidate preparation. Recheck these facts, S3 content, registry and images
before publication. Adoption of a parent without managed evidence performs a full
refresh and preserves prior splits only with unambiguous identity. Publish the same
three-file payload as standalone; managed tasks.yaml additionally embeds complete
source evidence and dataset.yaml embeds resolved class/split/image policy. No images
or archive are published; source evidence survives filtering/transformation.

The dataset command group supports list, show, versions, fetch, prepare, diff,
report-errors and publish, with prompt-free APIs and JSON inspection. Standalone
verification/preparation/publication remain available with their distinct split and
source rules. Preparation not ready exits 1; input/configuration/operational errors
exit 2. Ordinary verification exits 0 for passed/explicitly cleaned valid output,
1 for unresolved findings or cancellation, and 2 for errors. Standalone publication
exits 0 only after confirmed finalization, 1 for cancellation and 2 for blocked/failure.

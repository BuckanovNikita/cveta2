# Dataset and public interface reference

The [functional specification](../specs/baseline.md) describes the workflows and their
state and failure rules. This reference supplies detailed public formats, API values
and compatibility cases. Internal decomposition is replaceable.

## Public interfaces and diagnostic values

The [Python API guide](python-api.md) owns supported imports, signatures and return
types; the [CLI guide](cli.md) owns commands; [configuration](configuration.md) owns
fields, environment variables and defaults. Runtime compatibility is declared in
`pyproject.toml`. The functional specification owns [connection, retry and diagnostic
behavior](../specs/baseline.md#connections-configuration-and-failures).

`CvatApiError` accepts optional keyword-only `diagnostics`; the exceptions facade
exports neutral `CvatRequestDiagnostics`. Diagnostics contain actual failing HTTP
context, resource IDs, allowlisted correlation IDs and bounded sanitized summaries.
They are immutable neutral values with name/value identifier tuples, a timezone-aware
UTC timestamp and status 0 when unavailable; they retain no SDK objects. Cookies,
credentials and raw HTML are excluded.

## Dataset format and fetch

Full-fetch and fetch-task tables use the ordered 30-column `CSV_COLUMNS`
schema below. Types describe record values before CSV encoding; an empty cell is
missing. Ordinary dataset readers preserve literal text such as `NA` and `001`
while retaining numeric/boolean inference. Verification has the stricter lexical
reading contract described below.

| Column, in order | Type | Meaning |
| --- | --- | --- |
| `image_name` | `str` | Bare image basename |
| `image_width` | `int` | Width in pixels |
| `image_height` | `int` | Height in pixels |
| `instance_shape` | `"box" \| "none" \| "deleted"` | Record discriminator |
| `instance_label` | `str` | Box label; missing for empty/deleted rows |
| `bbox_x_tl` | `float` | Top-left x |
| `bbox_y_tl` | `float` | Top-left y |
| `bbox_x_br` | `float` | Bottom-right x |
| `bbox_y_br` | `float` | Bottom-right y |
| `task_id` | `int` | CVAT task identity and annotation recency |
| `task_name` | `str` | CVAT task name |
| `job_stage` | `str` | Owning regular job stage, or empty string |
| `job_state` | `str` | Owning regular job state, or empty string |
| `task_completed` | `bool \| None` | Completion of every live job; legacy missing/null supported |
| `task_updated_date` | `str` | Informational update timestamp; cache revision, never recency order |
| `created_by_username` | `str` | Annotation author |
| `frame_id` | `int` | Frame index within the task |
| `split` | `"train" \| "val" \| "test" \| None` | External dataset assignment |
| `subset` | `str` | CVAT task subset |
| `occluded` | `bool` | Occlusion |
| `z_order` | `int` | Stacking order |
| `rotation` | `float` | Rotation in degrees |
| `source` | `str` | Annotation source |
| `annotation_id` | `int \| None` | CVAT annotation ID |
| `confidence` | `float \| None` | Prediction confidence, including YOLO imports |
| `issue_text` | `str` | Frame issue comments; empty when absent |
| `issue_state` | `str` | Exported `open`/`resolved` states; `new` reserved for upload |
| `s3_image_path` | `str \| None` | Complete bucket-relative key, including frame subdirectories |
| `image_path` | `str \| None` | Absolute local image path |
| `attributes` | `dict[str, str]` encoded as JSON | Annotation attributes; Unicode preserved |

`BBoxAnnotation` supplies the full box record. `ImageWithoutAnnotations` supplies
image/task/frame/job/path metadata, optional split and frame issues, with
`instance_shape="none"`; absent box-specific fields become missing cells.
`DeletedImage` supplies image/task/frame/job/path metadata with
`instance_shape="deleted"`, default dimensions 0, missing split/issues/box
fields. Sparse records serialize `attributes` as `{}`. Internal `frame_path`
retains nested CVAT identity in models/cache but is not a CSV column.
`split` is always unset by fetch and ignored by CVAT upload; conversion or the
user supplies it. `subset` remains a separate CVAT field.

`TaskAnnotations` contains `task_id`, `task_name`, `annotations` and
`deleted_images`; `TaskAnnotations.merge()` produces `ProjectAnnotations` with
`annotations: list[AnnotationRecord]` and `deleted_images: list[DeletedImage]`.
`AnnotationRecord` is the box/empty-image union. `CvatClient.fetch_one_task()`
returns `TaskAnnotations | None`. `fetch` returns `PartitionResult` with
`dataset`, `obsolete`, `in_progress` DataFrames and `deleted_images` records;
`fetch_task` returns its unpartitioned annotation DataFrame.

### Output and partition rules

| Command/file | Contents |
| --- | --- |
| `fetch` / `dataset.csv` | Latest completed-task annotations for each non-deleted image |
| `fetch` / `obsolete.csv` | Stale completed-task annotations and annotations for images deleted by the winning task |
| `fetch` / `in_progress.csv` | Non-completed-task annotations |
| `fetch` / `deleted.csv` | Deletion records using the same CSV schema |
| `fetch --raw` / `raw.csv` | Full unprocessed annotation rows |
| `fetch-task` / `dataset.csv` | All selected task annotations without partitioning |
| `fetch-task` / `deleted.csv` | Selected tasks' deletion records |

CVAT job stages are `annotation`, `validation`, `acceptance`; states are `new`,
`in progress`, `completed`, `rejected`. Only `acceptance/completed` is finished.
A task is complete only when all its jobs are finished, including Ground Truth,
replica and jobs without exported frames. An explicit false `task_completed`
excludes the task even when exported rows look finished. Missing/null legacy
completion falls back to row stage/state, including deletion rows; unfinished
evidence wins over finished evidence.
Missing legacy stage/state is unfinished evidence for nullable pandas columns as
well as ordinary object columns; explicit completion precedence is unchanged.

Row stage/state comes from the regular annotation job owning its frame; uncovered
frames get empty strings. Ground Truth/replica jobs do not overwrite row ownership.
Overlapping regular jobs prefer unfinished positions, then the lowest job ID.
Among tasks for one image, highest `task_id` wins; deletion takes precedence over
annotation on a same-task tie. Project label edits can change every task timestamp,
so `task_updated_date` never orders partition or new-task selection.

`whats-new` reports completed tasks absent from completed membership in
`dataset.csv` and adjacent `obsolete.csv`/`deleted.csv`, including tasks completed
after export. Unfinished evidence keeps a task eligible. Missing/unreadable
siblings are skipped; legacy siblings lacking state columns retain ID membership.
The displayed cutoff is the highest completed task ID, falling back to the highest
usable ID, and is informational. Required baseline stage/state/task columns and
at least one usable task ID must exist; obsolete `task_status` CSVs need refetching.

Ordinary fetch does not create, write or remove `.tasks`; `save_tasks=True`
retains per-task debug CSVs. Full fetch prunes from its complete unfiltered task-ID
snapshot, obtained after any promotion, without a second inventory. Deletions after
the snapshot reconcile next run. Stage wall time is distinct from summed worker
time; cached/fetched/skipped/degraded totals explicitly report incomplete output.

For at most 2,000 uncached images, canonical S3 keys download with GET and no HEAD;
only missing-key replies enter listing/basename fallback. Larger batches list first;
images cached at their expected canonical destinations need zero S3 requests.
Stale frame names requiring basename fallback rediscover the alternate key each
run before checking its local file; cached alternate bytes are not downloaded again.
Request authorization/configuration and
exhausted connection failures abort; interrupted body/local writes count as failed
transfers, retaining retries, bounded worker memory and atomic writes. Filesystem
confinement/resolution is once per unique destination per enrichment pass; lexical
validation and symlink rejection remain.

### Geometry, identity and issues

Standalone rectangles retain their coordinates and rotation. Standalone polygons
become tight axis-aligned `(min_x, min_y, max_x, max_y)` boxes over every vertex,
with `rotation=0.0`, without rounding, clipping or retaining contours. Preserve
labels, attributes, IDs, author/source, occlusion, z-order, task/frame metadata
and issues. Warn for each approximation with task/annotation context. Fewer than
three coordinate pairs, odd counts, nonfinite coordinates or zero width/height
cause a contextual skip and per-task skipped-polygon summary. Repeated closing
vertices and out-of-image coordinates are allowed; no topology/area check or
source-rotation transform is applied. All-rejected frames retain empty-image
behavior. Tracks and other shapes remain unsupported and warn when skipped.

Frame paths are relative POSIX paths. Distinct images must have unique basenames
and unique stems across a project/dataset, directories and splits; repeated rows
or tasks for the same image are allowed. CSV `image_name` stays a basename while
S3 keys preserve subdirectories. Automatic collision detection is not guaranteed
outside these input constraints; duplicate-basename selection remains undefined.

Issues belong to frames, so exported issue fields repeat on every frame row.
One issue's comments join with `; ` in creation order. Multiple issues join with
` | ` in both fields, preserving positional correspondence. Embedded ` | ` in a
comment makes reverse splitting ambiguous. Upload creates issues only for rows
with `issue_state="new"`, nonempty text and a complete bbox; missing bbox warns
and skips instead of creating a full-frame issue. Identical image/text/bbox rows
deduplicate, distinct boxes retain distinct issues; exported open/resolved/empty
states do not create issues.

### Cache and explicit promotion

Task cache schema 5 rejects older local/S3 payloads, including schema 4, so cached
tasks refetch polygon boxes. Cache validity includes task identity, completion and
live `task_updated_date`; incomplete issue retrieval must not become a valid
completed-task cache. Polygon warnings occur during parsing, not cache hits.
`--force` bypasses reads while refreshing cache; `--no-cache` and
`CVETA2_DISABLE_CACHE` disable ordinary reads/writes/S3 synchronization. Invalid or
unreadable ordinary cache entries warn and fall back even when deletion/repair
fails. Current path derivation and project overrides remain in the cache guide.

Only project `fetch` has opt-in `--skip-validation` /
`skip_validation=False`; omitted means no promotion. Before completed-only
selection, inspect every non-ignored task's full nonempty job list. Qualify only
lists consisting entirely of `annotation/completed` and `acceptance/completed`;
job type and frame coverage do not narrow eligibility. Change only the former to
the latter; fully accepted tasks get no redundant writes, zero-job/ignored/other
tasks get none. Use bounded task concurrency and sequential updates within a task.

Before any job update, strictly invalidate the configured local entry and enabled
S3 mirror using the same project settings as fetch. Local invalidation remains
required with cache disabled, without S3 contact. Read/invalidation/update failures
identify available project/task/job context and abort before annotation retrieval,
downloads or new output. Join promotion workers before fresh metadata and ordinary
fetch; newly completed tasks appear in the same completed-only run. Successful
CVAT changes persist without rollback; rerun rechecks and updates only remaining
eligible jobs. Concurrent external edits/cache writers have no transaction guarantee.

## Upload, conversion and storage

CVAT upload validates finite complete labelled boxes before external writes;
empty and deletion-only inputs remain supported. Required manifest checkpoints
precede creation and attachment. Recovery schema 3 binds complete normalized
intent: annotation content/multiplicity, ordered frames, labels, attributes,
issues, deletions, behavior-affecting options and frozen storage/frame mapping.
Changed input or insufficient legacy manifests cannot authorize resume.

Known remote tasks must belong to the project and match frame order/path identity
and the exact semantic multiset of intended shapes. Partial/conflicting content
refuses append. Preserve available nested/full paths, allowing documented cloud
prefix omission; basename-only metadata permits unique-name comparison with a
warning, not proof of unavailable directory identity. Ambiguous creation or
replacement needs manual inspection, never automatic duplicate creation. Required
checkpoints fail closed; completed outcome persists before cleanup, whose failure
warns with successful task/stale path rather than losing success or duplicating it.
Resume preserves initial S3 mapping, reuses exact shapes, adds only missing issues,
and may repeat idempotent deletion/completion. Failed S3 uploads prevent creation.
When upload prompts resolve missing arguments, the echoed command retains a
requested `--resume` so copying it preserves recovery intent.

`UploadResult` fields are `task_id: int`, `task_name: str`, `url: str`, and integer
`images`, `deleted`, `annotations`, `issues`. `DownloadStats` has integer
`downloaded`, `cached`, `failed`, `total`; `UploadStats` has integer `uploaded`,
`skipped_existing`, `failed`, `total`. Each requested transfer has one outcome;
real boto3 upload-wrapper failures count while independent transfers finish.

CSV merge preserves literal deletion names, including `NA`. Expected CSV
read/parse/decode and YAML syntax/type/class-map failures become contextual
domain errors; unexpected failures propagate. Every exportable row needs
`train`, `val` or `test` before destination mutation. Repeat exports refresh image
bytes; same-file links remain valid. COCO replacement removes only prior
metadata-owned obsolete images/annotations/splits and preserves unrelated files.
Unsafe, missing or ambiguous cleanup ownership cannot authorize deletion. No
atomic rollback is promised after an unexpected output I/O failure; missing
images retain their documented warning behavior.

YOLO class IDs are nonnegative integers; numeric fields are finite, centers lie
in `[0,1]`, sizes in `(0,1]`, optional confidence in `[0,1]`. Malformed lines warn
with file/line context and skip independently of valid siblings; existing
extra-field detection compatibility validates every numeric field. YAML `path`
root resolution and sparse source ID/name mappings are preserved. The upload
helper rejects malformed maps/unknown IDs before remote creation. The clone helper
uses each source task's own images and explicit frame order; empty projects work.

S3 synchronization validates the complete canonical key/destination mapping
before writes, including symlink aliases and ancestor collisions. Noncanonical
or colliding destinations reject the entire sync. Only regular files count as
cached images; a directory destination fails and remains intact. Project names
become contained cache components by encoding unsafe/reserved parts without
changing logical names; safe names retain their spelling. Sync downloads missing
objects and never writes/deletes S3 objects. Explicit sync roots and configured
`sync_roots` apply to sync/fetch downloads, not CVAT upload's project storage.

## Standalone verification and prepared bundles

### Verification API and policy

`verify(path, *, profile="cveta2", options=None, output_dir=None, clean=False)`
reads one CSV. `verify_dataframe(frame, *, profile="cveta2", options=None)`
preserves caller data and indices. `schema_for(profile)` returns the non-coercing
schema. Profiles are exactly `cveta2` and `clearml-yolo`; unsupported profiles
fail explicitly. `ValidationOptions` rejects unknown fields and contains
`iou_threshold: float=0.99` in `(0,1]`, `check_images: bool=False`,
`image_root: Path | None=None`, `base_dir: Path | None=None`,
`emit_warnings: bool=True`.

Read UTF-8 CSV lexically, accepting a UTF-8 BOM and preserving literal cells and
column order. Empty/duplicate headers, wrong record widths and malformed input
fail; a valid header-only file is allowed. DataFrame header names must be unique
nonempty strings. Findings identify zero-based original row positions, never
DataFrame index labels. Extra columns and original rejected values are retained.
Schema/structural failures cannot be cleaned away.

The `cveta2` required headers are `image_name`, `image_width`, `image_height`,
`instance_shape`, `instance_label` and all four bbox coordinates. Known optional
CSV fields retain their typed/enum constraints; unknown extras warn but survive.
`clearml-yolo` requires `image_name`, `image_path`, `instance_label`, four bbox
coordinates and `split`; it also validates supplied `image_width`, `image_height`,
`width`, `height`, and otherwise preserves extras without treating them as
training fields. Box labels must be nonempty; cveta2 labels are strings, while
the training profile also accepts numeric labels. Empty/deleted records have
empty labels and all four coordinates empty. cveta2 permits deleted rows and
zero deleted-image dimensions; training rows represent boxes or backgrounds.

Validate finite coordinates, positive geometry, consistent dimensions, local
path/name ownership, image kinds and splits. cveta2 groups by image/task identity;
unscoped rows remain separate and mixed scopes warn. Training image ownership is
global. Malformed records quarantine their whole image group, including original
sibling rows. Missing upper bounds and ignored rotation in axis-aligned IoU are
reported, never inferred as checked. Image checks resolve canonical local paths,
decode each file once, account for EXIF orientation and never download URI paths.
`image_root` fills only absent path cells; relative paths resolve from CSV/base
directory. Requested but unavailable media inspection is an error.

Duplicate processing is deterministic in original row order: retain the first
representative, reject later full-row or threshold-IoU matches. cveta2 compares
complete rows and image/task boxes. Training duplicate comparison uses required
training fields within class; high-IoU cross-class conflicts quarantine the image.
Opaque/cyclic extras that prevent exact comparison warn and preserve their
values while IoU remains checked. Unknown bounds never imply successful checking.

Training box sides and area must exceed two. Only training-profile boxes with
trustworthy dimensions and no other blocking group errors may propose boundary
clipping: every overflowing edge must be strictly below ten pixels, and the
clipped result must still satisfy training geometry. Original broken evidence
is never replaced by repaired values. Verification defaults to report-only;
explicit cleanup accepts repairs and rejected-row removal without overwriting
input. `is_valid` describes absence of original rejected rows/structural errors;
`requires_cleanup` separately reports rejected rows or proposed clipping/class
canonicalization. A valid result may still require accepting repairs.

`ValidationResult` exposes `profile`, `clean`/`broken` DataFrames,
`clean_row_positions`/`broken_row_positions: tuple[int, ...]`,
`issues: tuple[Issue, ...]`, `input_row_count: int`,
`checked_checks`/`skipped_checks: tuple[str, ...]`, `structural_errors: bool`,
`input_image_count`/`clean_image_count: int`, and `is_valid`, `requires_cleanup`,
`warnings`, `reasons_for(row_position)`. `Issue` fields are `code: str`,
`message: str`, `severity: "error" | "warning"`, `row_position: int | None`,
`columns: tuple[str, ...]`, `related_rows: tuple[int, ...]`, `iou: float | None`.
`DatasetInputError` is both `Cveta2Error` and `ValueError`; `DatasetWarning` is
a warning type, not a successful-check claim.

### Reports and serialized metadata

Ordinary verification with an output directory writes `report.json` and
`broken.csv`; `clean.csv` exists only for explicit cleanup. Outputs use a new
directory; inputs are never overwritten. `report.json` contains:

| Key | JSON value |
| --- | --- |
| `profile` | `"cveta2"` or `"clearml-yolo"` |
| `is_valid`, `requires_cleanup`, `structural_errors` | Booleans |
| `counts` | Object with integer `input_rows`, `clean_rows`, `broken_rows`, `input_images`, `clean_images` |
| `clean_row_positions`, `broken_row_positions` | Arrays of original integer positions |
| `checked_checks`, `skipped_checks` | Arrays of check-name strings |
| `issues` | Objects with the exact `Issue` keys above; tuples encode as arrays |
| `metadata_columns` | Object mapping `row_position`, `reason_codes`, `reasons` to appended broken-CSV column names |

The appended names begin `__validator_row_position`, `__validator_reason_codes`,
`__validator_reasons`; append underscores until each avoids original-column
collisions. A bundle report omits `metadata_columns` and adds `blockers: list[str]`,
`ready: bool`, `broken_image_rows: int`, `class_changes: list[object]`.
Each class change has `kind: "added" | "renamed"`, `prod_id: int`, `name: str`,
`old_name: str | null`. `broken-images.csv` retains every original row of affected
images without replacing source values.

`dataset.yaml` and `tasks.yaml` are strict typed public payload metadata:

| Object/key | Type and meaning |
| --- | --- |
| `dataset.yaml.api_url` | `str`: public unauthenticated HTTP(S) class endpoint without embedded credentials |
| `dataset.yaml.classes` | `dict[str, ClassInfo]`: canonical name to stable identity/policy |
| `ClassInfo.prod_id` | `int`: class API `number`, not API `id` |
| `ClassInfo.empty` | `bool`, default false: exclude this class from training |
| `ClassInfo.alt_names` | `list[str]`, default empty: nonempty historical names |
| `dataset.yaml.images.local_root` | `list[str]`, default empty: independent local directories |
| `dataset.yaml.images.s3_root` | `list[str]`, default empty: independent approved S3 prefixes |
| `tasks.yaml.included` | Sorted unique nonnegative integer IDs represented by retained dataset rows |
| `tasks.yaml.obsolete` | Sorted unique nonnegative IDs of completed tasks fully superseded by fetch evidence |

Canonical class names/aliases cannot be empty or ambiguous; unknown metadata
keys and duplicate/recursive YAML structures are rejected. The API class record
uses `id: int`, `number: int`, `name: str`, `techClass: bool`,
`isPeriodical: bool`, `isCritical: bool`, `threshold: float`; additional API fields
may be ignored. Names are nonempty and thresholds finite. Persisted metadata
contains no authentication secrets.

### Standalone preparation and review

`prepare_dataset(source, *, output_dir, options)` requires all four exact full-fetch
files: `dataset.csv`, `obsolete.csv`, `in_progress.csv`, `deleted.csv`, including
valid header-only files. Capture their bytes before parsing. For standalone preparation, split assignment is
external; every retained image has one supported split, train and val are
nonempty, and train contains a training box. Val may contain only backgrounds.
All input `dataset.csv` rows need valid splits; cleanup cannot supply missing choices.

Reconcile classes by stable API `number`, retaining historical aliases and empty
policy on rename. Missing parent identities or ambiguous mappings block. Unknown
and empty classes quarantine whole images. New identities/renames require explicit
acceptance; unresolved choices become `MissingDecisions.decisions`, never API
prompts. `Decision` has `kind` (`dataset_name`, `api_url`, `class_empty`,
`class_changes`, `local_roots`), `message: str`, `choices: tuple[str, ...]`,
`class_id: int | None`.

`PrepareOptions` rejects unknown fields and contains `project: str`,
`dataset_name: str | None=None`, `api_url: str | None=None`,
`local_roots`/`s3_roots: tuple[str, ...]=()`, `class_empty: dict[int, bool]={}`,
`accept_default_classes: bool=False`, `accept_class_changes: bool=False`,
`clean: bool=False`. Default-class acceptance assigns false to remaining new
empty decisions; it does not silently accept class changes or cleanup. CLI
interaction belongs outside application code; `--non-interactive` requires all
decisions. Root and empty-class options repeat.

Validate every configured root and source-path coverage before filtering, with
symlink confinement. Local/S3 roots are independent lists without inferred mirror
relationships. S3 accepts approved URIs and bucket-relative keys only when the
bucket is unambiguous; per-object probing is not required. Images must be absolute
readable local files, successfully decoded with EXIF-aware sides at least ten
pixels. Supported filename extensions are `avif`, `bmp`, `dng`, `heic`, `heif`,
`jp2`, `jpeg`, `jpg`, `mpo`, `png`, `tif`, `tiff`, `webp`; decoded formats must
also be supported (`jpeg2000` is accepted). Bundle media checks are mandatory;
partial image checks, custom image-root and nondefault IoU overrides are not
bundle options.

Included task IDs come from retained source task/image pairs. Obsolete IDs require
completed tasks absent from included IDs and strictly newer completed annotation
or deletion evidence for every represented image across all four tables.
Unfinished/unknown completion or presence in `in_progress.csv` prevents completed
classification. Validation rejection does not erase supersession evidence;
filtered-only tasks are not automatically obsolete. Task-ID recency, explicit
completion and deletion precedence remain authoritative.

Preparation creates a new directory outside the source directory, refuses existing
paths/symlinks and writes these local artifacts:

| Path | Contract |
| --- | --- |
| `sources/{dataset,obsolete,in_progress,deleted}.csv` | Exact captured source bytes |
| `report.json`, `broken-images.csv` | Diagnostics, decisions and original affected-image rows |
| `dataset.csv` | Ready-only retained and explicitly accepted rows with canonical classes |
| `dataset.yaml`, `tasks.yaml` | Ready-only metadata and derived task manifest |
| `preparation.json` | Ready-only versioned binding of destination, parent, decisions and hashes |
| `preparation.sha256` | SHA-256 of exact preparation-record bytes; completion marker written last |

`PreparedDataset` exposes `directory: Path`, `ready: bool`, `validation`,
`metadata`, `tasks`; only ready bundles can upload. `BundleValidation` exposes
`result: ValidationResult`, `broken_images: DataFrame`, `blockers: tuple[str, ...]`.
Unresolved findings may leave diagnostic/source evidence but no uploadable payload.
Correct inputs/options, prepare a new directory, then review it before a separate
upload on the same machine. Preparation itself creates no remote child.

Standalone `preparation.json` keys are exactly `format_version: 1`, `options: PrepareOptions`,
`parent_id: str | null`, `parent_version: str | null`,
`source_hashes: dict[str, str]`, `payload_hashes: dict[str, str]`.
Hash-map keys are exactly the four source filenames and three payload filenames
respectively; values are SHA-256 strings. Options serialize tuples as arrays and
integer class-map keys as JSON object keys. The separate checksum detects
accidental record edits; it is not a signature against deliberate rewriting by a
machine owner.

### Standalone publication and exit codes

`upload_dataset(prepared_dir)` / `cveta2 upload-dataset PREPARED` accepts only a
prepared directory, never mutable sources or cleanup overrides. Read and hash
bound source/payload bytes and the preparation checksum; rederive and compare
payload/tasks, revalidate rows/media, roots, current classes and the latest exact
parent. Mismatch or unavailable prerequisite requires preparation again before
child creation. Publish a stable copy of the checked bytes, not files reread after
validation.

Parents match exact project/name, are finalized and nonarchived, and must contain
metadata; a CSV-only legacy parent blocks and requires a new dataset name. A newer
parent also requires preparation again. Do not modify parents. Remove inherited
child files/links, synchronously upload exactly `dataset.csv`, `dataset.yaml`,
`tasks.yaml`, finalize and verify success. Never publish images, local checksums/records or diagnostics. Standalone
publication excludes source snapshots; managed publication embeds source evidence
in its versioned tasks.yaml extension. A failure after creation reports the known
child ID without claiming finalization; inspect remote state before retrying.
`Publication` returns `dataset_id: str`, `version: str | None` after success.

| Command | Exit 0 | Exit 1 | Exit 2 |
| --- | --- | --- | --- |
| `verify` | Passed or explicitly cleaned valid outcome | Unresolved findings or cancellation | Input/configuration/operational error |
| `upload-dataset` | Confirmed finalization | Cancellation | Blocked or failed publication |

Fetch never initializes/publishes to ClearML. `publish_clearml`, `--no-clearml`,
`setup-clearml`, automatic mappings/settings and `CVETA2_CLEARML` are removed
without a compatibility period. Old configuration files are not rewritten;
obsolete automatic settings do not restore publication. CVAT `upload` remains a
separate supported operation. Standalone preparation requires externally assigned
splits; [managed preparation](../specs/baseline.md#managed-datasets) assigns them. Neither workflow
authorizes automatic end-to-end publication, remote deployment or a cryptographic
review system.

## Managed dataset formats and operations

The functional specification owns [managed configuration, migration, source reuse,
transformation, splits, feedback and publication](../specs/baseline.md#managed-datasets),
including first publication when the ClearML destination does not exist. The following
is the serialized and API reference for that workflow.

### Configuration representation

Personal and shared files each use `schema_version=1`. Personal configuration contains
credentials/auth references, local image/task-cache paths, network/runtime settings and
`project_config`. Shared configuration contains CVAT host/organization, stable project
IDs, source interpretation/S3 roots, task exclusions, dataset source memberships,
ClearML destination, class registry/exclusion policy, split policy and overlap decisions.

Personal file selection is `--config`, then `CVETA2_CONFIG`, then the configured default.
Shared selection is `--project-config` or the explicit API argument, then
`CVETA2_PROJECT_CONFIG`, then the saved personal reference. The CLI attachment and
migration operations are `setup --project-config` and `setup --migrate-config`.

Source types are `cvat` and `s3-csv`; CVAT sources reference the shared project registry.
S3 sources identify exact `s3://bucket/key.csv` objects. Captured metadata includes
SHA-256 of bytes and available opaque ETag/version identity. Required CSV fields are
`image_name`, `image_path`, `instance_label` and the four bbox coordinates; `split` may
be absent. Extra fields and explicit source lineage are retained. Managed configuration
models reject unknown keys.

### Managed fetch directory

Managed fetch writes a new directory, refusing an existing path, and links its files
into place only after staging all of them:

| Path | Contract |
| --- | --- |
| `dataset.csv` | Combined annotations of all sources with provenance columns |
| `sources/<source-name>/{dataset,obsolete,in_progress,deleted}.csv` | Captured partitions of each source; S3 sources fill only `dataset.csv` |
| `source-snapshot.yaml` | Typed `format_version=1` snapshot: definition and registry hashes, pinned parent, per-source tables, task facts, label fingerprint and S3 object identity |

Source names match `[A-Za-z0-9][A-Za-z0-9_-]*`. The provenance columns `source_id`,
`source_project_id`, `source_task_id`, `source_frame_id` and `source_row_id` are
reserved: a source CSV that already contains any of them is rejected. `source_id` is
the source name; project, task and frame IDs are filled only from CVAT source identity
and stay empty for S3 rows. `source_row_id` is `<source-name>:<SHA-256 of the row>:<n>`,
where `n` counts identical rows.

### Publication and preparation records

The three-file payload uses `dataset.csv` for accepted transformed rows and assigned
splits. `dataset.yaml` embeds resolved class/split/image policy. The typed versioned
managed extension of `tasks.yaml` contains CVAT/S3 source evidence: tasks, label
definitions, all four original partitions, empty-task facts, object hashes and the
registry snapshot. Files without managed extensions remain readable.

Managed local preparation uses `format_version=2` and binds captured sources,
transformed CSV, payload hashes, media, the relevant resolved shared definition and
exact parent. The format differs from standalone `format_version=1`; the behavior and
freshness rules are owned by the managed specification linked above. Feedback delivery
keeps its receipts in the preparation's `feedback.json`, separate from the payload: intent
is recorded before each CVAT issue write and acknowledged afterwards, so an interrupted
delivery resumes without duplicating issues.

### Public operations

The dataset CLI group exposes `list`, `show`, `versions`, `fetch`, `prepare`, `diff`,
`report-errors` and `publish`. Corresponding API functions are `list_datasets`,
`show_dataset`, `dataset_versions`, `fetch_dataset`, `prepare_managed_dataset`,
`compare_datasets`, `report_dataset_errors` and `publish_dataset`. They accept shared
selection independently and support JSON inspection. The functional specification
owns readiness and exit behavior.

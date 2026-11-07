# cveta2: problem and desired behavior

## Problem

Dataset maintainers need to turn changing CVAT annotations and external CSV sources
into reproducible training datasets without losing lineage, overwriting unrelated
annotations, mixing train/test content or publishing unchecked bytes. They also need
predictable errors and efficient incremental exports across unreliable services.

## Desired outcome and scope

Provide a prompt-free Python API and a Russian CLI for fetching, validating, converting,
reviewing and explicitly publishing datasets. Preserve source evidence separately from
user transformations, make repairs and remote writes explicit, and reject ambiguity
before mutation. This document states required behavior, not implementation progress.

The [engineering guidance](../.specify/memory/engineering.md) owns development and
verification procedures; the [constitution](../.specify/memory/constitution.md) and
[architecture reference](../.specify/memory/architecture.md) govern implementation.

## Capability specifications

- [fetch speed diagnostics](001-fetch-speed-diagnostics/spec.md).
- [nullable completion](002-nullable-completion/spec.md).
- [operational errors](003-operational-errors/spec.md).
- [managed datasets](004-managed-datasets/spec.md).
- [docker internal stands](005-docker-internal-stands/spec.md).

## Acceptance boundaries

Acceptance requires the scenarios and rejection conditions in the contracts below.
A successful local/mock check does not certify remote mutation, outage recovery or
publication. Validate those outcomes on explicitly owned live resources.
Unsupported tracks, ambiguous duplicate basenames, cross-job transactions and generic
rollback after arbitrary output I/O failure are outside the promised behavior.
Basename-only remote metadata provides limited identity evidence; local review hashes
do not defend against a hostile owner. These limits do not waive ordinary write safety.

## Product and public interfaces

cveta2 is a Python >=3.12,<3.14 CLI and API for CVAT projects: fetch annotations
and images, partition and convert datasets, upload to CVAT, manage labels and
tasks, compare completed-task membership, inspect CSVs, and explicitly prepare
and publish reviewed datasets to ClearML. Python 3.12 and 3.13 are supported;
3.10, 3.11 and >=3.14 are excluded. Development remains on Python 3.12; Ruff's
conservative syntax target is not an additional runtime support promise.
ClearML is optional; ordinary CSV verification requires neither CVAT nor ClearML.

Supported public module paths and model identities remain compatible:
`cveta2`, `cveta2.api`, `cli`, `client`, `config`, `dataset_partition`,
`exceptions`, `fs_utils`, `image_downloader`, `image_uploader`, `models`,
`projects_cache`, `s3_types`, `s3_utils`, `task_cache` and `upload_manifest`
under the `cveta2` package. Unsupported old `_client`, `_client_ops`, `services`,
`_clearml` and `commands` package paths are retired. Public facades contain no
business policy and canonical modules do not depend on them.

Public workflows include `fetch`, `fetch_task`, `upload`, `merge`, `whats_new`,
`s3_sync`, `get_labels`, `update_labels`, `ignore`, `task_mark_deleted`,
`task_drop_label`, `task_delete`, `task_set_status`, `convert_from_yolo`,
`convert_to_yolo`, `convert_to_coco`, `partition_annotations_df`, `verify`,
`verify_dataframe`, `schema_for`, `prepare_dataset` and `upload_dataset`.
Supported signatures, options, return models and runnable examples are maintained
in the [Python API guide](../docs/python-api.md); public functions never prompt or
exit. Expected operational failures use `Cveta2Error` and its typed subclasses;
unexpected implementation errors remain visible.

`Connection` accepts optional `host`, `username`, `password`, `organization`,
`config_path` and an already usable `client`. Explicit values override environment,
selected file and preset; `organization=""` explicitly selects the personal
workspace. Injected clients/sessions remain caller-owned; owned sessions close
deterministically. `CvatClient` retains lazy credential checking when entering
its owned session.

CVAT selectors accept numeric IDs or names scoped to their project/organization;
`ORG/PROJECT` selects an organization and `/PROJECT` the personal workspace.
Ambiguous names fail with matching IDs before mutation; an active client uses
the authoritative scoped project list. Cached disconnected queries remain
supported. `verify --bundle --project` instead names the exact ClearML project.

Procedures and complete option inventories remain in these maintained guides:

| Procedure | Current reference and section |
| --- | --- |
| Install, configure, contribute, merge and release | [README](../README.md), [engineering guidance](../.specify/memory/engineering.md) |
| Fetch, promote jobs, compare tasks | [CLI guide](../docs/cli.md), `fetch`, `fetch-task`, `whats-new` |
| Upload and recover an interrupted CVAT upload | [CLI guide](../docs/cli.md), `upload` and `--resume` |
| Convert CSV/YOLO/COCO; manage labels/ignore/tasks | [CLI guide](../docs/cli.md), the corresponding command sections |
| Verify, explicitly clean, prepare, review, publish | [CLI guide](../docs/cli.md), `verify` and `upload-dataset`; [API guide](../docs/python-api.md), verification/publication examples |
| Configuration, environment, retries, noninteractive use | [Configuration guide](../docs/configuration.md) |
| Image paths, annotation cache and ClearML prerequisites | [Images and cache guide](../docs/images-and-cache.md) |
| Development tools: changed-function mutation check, fetch benchmark, and where the other helpers live | [Scripts guide](../scripts/README.md) |

### Configuration and failures

Configuration resolves explicit API values, then environment, the selected YAML
file (`CVETA2_CONFIG` or the default `~/.config/cveta2/config.yaml`), then the
bundled preset. The maintained configuration guide owns all fields, environment
variables and defaults. Custom config selection also selects adjacent project
cache state and appears in credential diagnostics. CLI YAML/type/value errors
are actionable, omit credential values and do not produce incidental tracebacks;
API callers retain typed errors.

Malformed YAML diagnostics name the file, error category and available one-based
line/column without including source excerpts or scalar values. The original
parser exception remains available as the cause for explicit API debugging.

Unset/zero data timeout means no timeout; positive values set the read timeout
with a ten-second connect timeout. Negative/nonfinite values fail validation.
Noninteractive operation replaces missing choices with errors and follows the
command-specific requirements in the configuration guide; it never authorizes
overwriting an existing verification/preparation directory.

CVAT reads retry configured transient failures; non-idempotent create/append
writes retry refused 429 responses, never ambiguous 503 responses, including
ones carrying `Retry-After`. Idempotent deletion/job-state replacement retains
its retry policy. Exhausted 429 errors abort fetch; ordinary per-task 5xx failures
warn, identify skipped tasks and continue unless `CVETA2_RAISE_ON_FAILURE` is
enabled. S3 authorization/not-found failures are not indiscriminately retried.
Only finite nonnegative `Retry-After` delta-seconds are accepted; negative,
nonfinite, missing, unparseable and HTTP-date values use ordinary backoff.
Exhausted SDK 502/503/504 responses retain their final status and follow this
task policy, rather than becoming unidentified transport failures. Optional
issue-read failures remain degraded results. `CvatApiError` accepts optional
keyword-only `diagnostics`, with neutral `CvatRequestDiagnostics` exported from
the exceptions facade. Actual failing HTTP context, UTC time, status, resource
IDs, allowlisted correlation IDs and bounded sanitized summaries are available;
credentials/cookies/raw HTML are excluded. Retry logs count cveta2 attempts,
not all underlying HTTP attempts. Configured retry budgets, SDK interaction and worker settings remain documented
in the configuration guide.

`doctor` returns 0 when required CVAT configuration checks succeed and 1 when
they fail or cannot run. Optional AWS/image-cache/cache warnings and disabled
checks do not fail it. This is configuration diagnosis, not a guarantee of live
CVAT network health. Stored ignored numeric task IDs can be removed by CLI/API
without requiring that remote task to exist; names/unknown IDs still resolve
remotely and project resolution remains required.

Task mark-deleted counts only requested frames not already deleted. An entirely
redundant request returns zero without a CVAT metadata PATCH.

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

## Verification and prepared bundles

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

### Preparation and review

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

`preparation.json` keys are exactly `format_version: 1`, `options: PrepareOptions`,
`parent_id: str | null`, `parent_version: str | null`,
`source_hashes: dict[str, str]`, `payload_hashes: dict[str, str]`.
Hash-map keys are exactly the four source filenames and three payload filenames
respectively; values are SHA-256 strings. Options serialize tuples as arrays and
integer class-map keys as JSON object keys. The separate checksum detects
accidental record edits; it is not a signature against deliberate rewriting by a
machine owner.

### Publication and exit codes

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
separate supported operation. No split generation, automated end-to-end pipeline,
remote deployment or cryptographic review system is implied.

## Architecture and acceptance

Preserve inward dependencies: public facades -> interfaces -> composition ->
adapters -> application -> domain; composition may construct/inject inner values.
Application owns typed ports and receives settings/effects explicitly, without
configuration discovery, concrete client creation or a service locator. Domain
owns pure policies. CVAT, S3, config, class-API and ClearML adapters retain their
declared independence and SDK ownership; canonical siblings remain acyclic.
Inner imports do not eagerly load infrastructure. Filesystem/environment/network,
clocks, execution and prompts remain at their owned outer boundaries.

Execution returns input-ordered outcomes; explicitly caught per-item failures
remain outcomes, while uncaught failures cancel queued work and join active work
before propagation. Preserve source/storage schemas, public aliases, recovery
ordering, Unicode handling, effects and mutation scope during internal cleanup.
The maintained architecture reference and executable contracts own detailed module
assignments rather than this snapshot freezing implementation file layouts.

Mutation testing (development tooling, constitution 2.0.0) mutates the functions a
commit changes in an isolated per-run workspace and reports survivors without
blocking; tool or clean-test failures fail the commit.

Current acceptance requires the behavior above and the applicable repository
gates, with positive and negative architecture checks. Changes need current
documentation, task-owned architecture evidence, appropriate regression/mutation
and live checks, fresh independent review when required, and convergence before
authorized Git-only delivery. A passing ordinary suite is not evidence that
unexecuted mutation/live/platform checks passed. The checklist for future changes
includes these boundary scenarios:

| Area | Preserved acceptance |
| --- | --- |
| Fetch/data | Exact CSV order/types; task completion fallback; same-task deletion; ID recency; polygon edge cases and cache refresh |
| Promotion/recovery | No excluded writes; strict invalidation; no output after promotion failure; partial-write retry without duplicates |
| Upload/storage | Ambiguity/changed intent fail before mutation; exact remote reconciliation; mandatory checkpoints; safe paths and truthful outcomes |
| Conversion | Literal names; prewrite split validation; current image bytes; owned-only cleanup; contextual malformed-input diagnostics |
| Verification | Both profiles; original positions/values; quarantine, duplicate/class policy; explicit repairs; truthful skipped checks |
| Preparation/publication | Four exact sources; choices/roots/trainability; derived task IDs; tamper/prerequisite blocking before child creation; exact finalized payload |
| Public/tooling | Supported imports/signatures; prompt-free API; documented CLI exits/config; isolated wheel behavior on supported interpreters; enforced inward effects |

## Managed dataset configuration and lifecycle

### Strict configuration ownership

Personal and shared files are separately versioned with schema_version=1. Personal
configuration owns credentials/auth references, local image/task-cache paths,
network/runtime settings and the project_config reference. Shared configuration
owns CVAT host/organization, stable project IDs, source interpretation/S3 roots,
task exclusions, dataset source memberships, exact ClearML destination, class
registry/exclusion policy, split policy and overlap decisions. Personal fields do
not overlay shared policy, including values equal to shared values.

Resolve personal selection explicit --config > CVETA2_CONFIG > the existing
default. Resolve exactly one shared file explicit --project-config/API argument >
CVETA2_PROJECT_CONFIG > saved personal reference. Saved relative references are
anchored to the personal file directory; explicit/environment relative paths use
the working directory. Invalid selected files fail without fallback. Environment
credential/runtime settings remain supported; conflicting CVAT identity overrides
are rejected. Standalone legacy authentication-only configuration remains readable.

setup --project-config validates and attaches without rewriting the shared file
or asking for credentials. Ordinary setup offers attachment. setup --migrate-config
previews a redacted field split and requires verification before activation. Move
mixed-section fields individually; keep unknown values in the original backup and
report unresolved fields/identities. Never invent project IDs from names, silently
restore retired automatic mappings or overwrite an existing differing shared file.
Preserve a private original backup and recover an interrupted approved shared-first
activation from its journal. Cancellation is a no-op; repeated migration is
idempotent. Noninteractive callers cannot auto-approve migration. Explicit policy
writers update shared storage or fail if read-only; local-path writers stay personal.

### Managed sources and transformation

A named dataset combines one or more cvat or s3-csv sources. Source aliases and
references are unique inside a definition; exact ClearML destination pairs are
unique across definitions. CVAT sources reference the shared project registry.
The first managed implementation uses one configured CVAT server/organization.

Pin the latest finalized, nonarchived parent. Check live task completion and
updated_date before reusing published unchanged completed task evidence without
annotation downloads. Refresh changed/new/reopened tasks, account for deleted
ones, and invalidate project reuse after CVAT label changes. Registry changes
conservatively invalidate CVAT reuse across the dataset. --refresh bypasses reuse.
Preserve original per-task evidence, including empty tasks and rows lost during
project partitioning; task-ID recency and same-task deletion precedence remain
source-project local. Missing mandatory sources fail assembly.

S3 sources are exact s3://bucket/key.csv annotation objects, captured with SHA-256
of bytes and available opaque ETag/version metadata. Required annotation fields
are image_name, image_path, instance_label and four bbox coordinates; split may be
absent. Retain extra fields and explicit source lineage without manufacturing CVAT
task IDs. Each fetch captures the CSV; changed objects replace their entire source
contribution. Referenced images are not downloaded and must be locally available
before verification.

Fetch emits separate source evidence and combined annotations in a new directory.
The user runs any transformation script externally. Preparation accepts its CSV
without restricting operations or requiring one-to-one source/output rows. Raw
source evidence remains independent. Untraceable output lineage is reported as
unmapped rather than guessed from filenames or row positions.

### Splits, preparation and feedback

Managed preparation assigns train/val/test before validation, default targets
0.6/0.2/0.2 and seed 42. Preserve published assignments by image-content SHA-256;
new images use deterministic seeded hashing. Targets do not guarantee exact
counts. Identical content never crosses splits. Replace/report script-provided
splits. Do not silently rebalance; split policy changes require a new lineage.
Keep existing nonempty train/val and training-box viability constraints.

Content overlaps require explicit source selection or exclusion, bound to the
participating source names. Changed membership requires renewed resolution.
Different content sharing an image filename blocks preparation. Apply existing
training/image/class validation and quarantine. Explicit --clean accepts proposed
repairs and removal; structural failures remain blocking.

Create review issues only for findings with unambiguous original CVAT
project/task/frame lineage. Group reasons by frame and use original coordinates
only when reliably traced. Preserve annotations/job status/human issues. Stable
markers and existing-issue reads make retries deduplicated. Record created,
already-present, failed and unmapped findings; mapped delivery failures block
publication, unmapped/S3-only findings remain local. Never accept arbitrary
S3 task-like cells as permission for feedback. Own issue-only metadata changes
must not create a false stale-annotation loop.

### Managed persistence and public operations

Payload inventory is exactly dataset.csv, dataset.yaml and tasks.yaml. The CSV
contains accepted transformed training rows and managed splits. Existing strict
metadata models accept optional typed versioned managed extensions; old files
remain readable. dataset.yaml embeds resolved mapping/split/image policy.
tasks.yaml embeds complete CVAT/S3 source evidence: tasks, label definitions,
all four original partitions, empty-task facts, object hashes and registry
snapshot. No ZIP or images are published. Raw evidence is retained even when
transformation or validation discards training rows.

A format_version=2 local preparation binds captured sources, transformed CSV,
payload hashes, media, relevant resolved shared definition and exact parent.
Only relevant definition changes invalidate it; unrelated shared entries do not.
Recheck parent, source facts, S3 content, registry, roots, images and prepared
bytes before publishing a stable checked copy. Legacy adoption performs one full
source refresh and preserves prior splits only where identity is unambiguous.
Parents are never modified.

The dataset CLI group exposes list/show/versions/fetch/prepare/diff/report-errors/
publish. APIs are prompt-free: list_datasets, show_dataset, dataset_versions,
fetch_dataset, prepare_managed_dataset, compare_datasets, report_dataset_errors
and publish_dataset. Shared selection accepts an explicit independent API argument.
Outputs include JSON inspection; prepare ready=false exits 1 and operational/
configuration failures exit 2. The standalone verify/prepare/upload interfaces
retain their existing contracts apart from the explicit configuration-ownership
migration.

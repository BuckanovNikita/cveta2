# cveta2 specification baseline

This is the current product and data contract consolidated on 2026-10-21 from
released behavior through v0.11.0, inspected at
`f6717f0211169f8f94c78da2bfa8dee86bfab602`. It replaces the retired numbered
specifications as the starting point for new work; it does not reset application
versions, Git history, compatibility, or verification requirements. New feature
records begin at `001` and state their changes to this baseline explicitly.

The [constitution](../.specify/memory/constitution.md),
[engineering guidance](../.specify/memory/engineering.md), and
[architecture reference](../.specify/memory/architecture.md) remain authoritative
for development, dependencies, effects, checks, ownership and release. English
specifications coexist with Russian user guides and CLI output. Archived plans,
task checkboxes and review suggestions are historical evidence, not a current
work queue. [Status and provenance](#status-and-provenance) distinguish completed,
superseded and deliberately unsupported behavior.

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
| Install, configure, contribute, merge and release | [README](../README.md), [CONTRIBUTING](../CONTRIBUTING.md) |
| Fetch, promote jobs, compare tasks | [CLI guide](../docs/cli.md), `fetch`, `fetch-task`, `whats-new` |
| Upload and recover an interrupted CVAT upload | [CLI guide](../docs/cli.md), `upload` and `--resume` |
| Convert CSV/YOLO/COCO; manage labels/ignore/tasks | [CLI guide](../docs/cli.md), the corresponding command sections |
| Verify, explicitly clean, prepare, review, publish | [CLI guide](../docs/cli.md), `verify` and `upload-dataset`; [API guide](../docs/python-api.md), verification/publication examples |
| Configuration, environment, retries, noninteractive use | [Configuration guide](../docs/configuration.md) |
| Image paths, annotation cache and ClearML prerequisites | [Images and cache guide](../docs/images-and-cache.md) |
| Operator clone, fixture-export and source-upload helpers | [Scripts guide](../scripts/README.md) |

### Configuration and failures

Configuration resolves explicit API values, then environment, the selected YAML
file (`CVETA2_CONFIG` or the default `~/.config/cveta2/config.yaml`), then the
bundled preset. The maintained configuration guide owns all fields, environment
variables and defaults. Custom config selection also selects adjacent project
cache state and appears in credential diagnostics. CLI YAML/type/value errors
are actionable, omit credential values and do not produce incidental tracebacks;
API callers retain typed errors.

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
Configured retry budgets, SDK interaction and worker settings remain documented
in the configuration guide.

`doctor` returns 0 when required CVAT configuration checks succeed and 1 when
they fail or cannot run. Optional AWS/image-cache/cache warnings and disabled
checks do not fail it. This is configuration diagnosis, not a guarantee of live
CVAT network health. Stored ignored numeric task IDs can be removed by CLI/API
without requiring that remote task to exist; names/unknown IDs still resolve
remotely and project resolution remains required.

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
valid header-only files. Capture their bytes before parsing. Split assignment is
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
`tasks.yaml`, finalize and verify success. Never publish images, source snapshots,
local checksums/records or diagnostics. A failure after creation reports the known
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

## Status and provenance

At the 2026-10-21 consolidation, current implementation, checked tasks, later
integrated closure and release evidence establish no remaining required product
work from the retired records. Earlier pending statements describe intermediate
handoffs; later closures supersede them. This conclusion is scoped to those
records and does not claim a new exhaustive audit or that all platforms were
tested. Cleanup/cutover verification is recorded separately with its own task.

| Retired work | Reconciled disposition and decision source |
| --- | --- |
| `001-project-documentation` | Completed documentation/governance migration; this baseline supersedes its dataset-contract location. [Original contract and evidence](https://github.com/BuckanovNikita/cveta2/tree/f6717f0211169f8f94c78da2bfa8dee86bfab602/specs/001-project-documentation) |
| `002-cvat-write-safety`, `003-dataset-correctness`, `004-storage-interfaces` | Implemented, verified and released in v0.7.0; all 26 October findings reconciled, including three clarified contracts and the simulated retry risk. [Remediation](https://github.com/BuckanovNikita/cveta2/commit/a6d3d6672b918649a9a2442527872041a56ac22c), [ledger and integrated evidence](https://github.com/BuckanovNikita/cveta2/blob/f6717f0211169f8f94c78da2bfa8dee86bfab602/specs/004-storage-interfaces/evidence/remediation-ledger.md) |
| `005-polygon-bboxes` | Implemented, verified, released v0.8.0. [Implementation](https://github.com/BuckanovNikita/cveta2/commit/41c045e76757b6af65687fe7da49a4e7aa30218d) |
| `002-fetch-skip-validation` | Implemented, verified, released v0.9.0. [Implementation](https://github.com/BuckanovNikita/cveta2/commit/a1e92b98f04d7965b79b2ea6b561a17d83aeb50f) |
| `006-clean-architecture` | Implemented, verified, released v0.9.1. [Implementation](https://github.com/BuckanovNikita/cveta2/commit/d67a83aed079dbc484c5e57678800e850687a4ed); its automatic-publisher contract and old interpreter target are superseded below. |
| `python-workflow-alignment` | Governance/documentation alignment completed and delivered; final delivery follows intermediate pending notes. [Evidence](https://github.com/BuckanovNikita/cveta2/blob/f6717f0211169f8f94c78da2bfa8dee86bfab602/docs/plans/python-workflow-alignment/verification-2026-10-14.md) |
| `007-python-support-window` | Implemented, verified, released v0.10.0. [Implementation](https://github.com/BuckanovNikita/cveta2/commit/7f91109ddd36e85ff7912fddafb7136d6700959b); the old wider support window is superseded. |
| `008-dataset-verification-publication` | Implemented, verified, released v0.11.0; T028/T029 and companion guidance delivery closed. [Implementation](https://github.com/BuckanovNikita/cveta2/commit/78138b80af33e2651711b399cd428aad646b431c), [delivery/convergence](https://github.com/BuckanovNikita/cveta2/blob/f6717f0211169f8f94c78da2bfa8dee86bfab602/specs/008-dataset-verification-publication/evidence/delivery-2026-10-20.md) |

Deliberate dispositions remain: unsupported tracks (BR-02); unique basename/stem
input constraints and undefined duplicate-basename selection (BR-03/05); no
cross-job/remote-edit transaction; limited identity proof with basename-only
server metadata; no generic rollback after arbitrary output I/O failure; local
review checksum rather than hostile-owner protection. The old `setup-clearml`
persistence requirement (UI-004) was implemented historically, then superseded by
explicit publication and removal of the wizard. A waiver or unsupported-input
decision is not a tested success. Historical conditional CVAT outage evidence
used injected failures; it is not a claim of a naturally observed outage. Dated
evidence retains platform, integration and agent-interaction limits rather than
turning them into newly promised functionality.

### Archive recovery

Checkpoint: `af0073e5bd8a8799f0cfd322cfb27c8efd7b747d`. The
[complete archive manifest](https://github.com/BuckanovNikita/cveta2/blob/af0073e5bd8a8799f0cfd322cfb27c8efd7b747d/archive/manifest.json)
records each original path, storage location, size, mode and SHA-256. It covers
107 former `specs/` files, three old `docs/plans/` files and 129 originally
untracked `bugs/` files. Tracked historical documents remain directly accessible
at that checkpoint; the original bug tree is contained byte-for-byte in
`archive/legacy-bugs.tar.gz`. The archive/checkpoint is historical evidence, not
current application source or a test suite. No executable fixture relocation was
needed; maintained fixtures remain under `tests/`.

```bash
git show 'af0073e5bd8a8799f0cfd322cfb27c8efd7b747d:specs/002-cvat-write-safety/spec.md'
git ls-tree -r af0073e5bd8a8799f0cfd322cfb27c8efd7b747d -- specs/ docs/plans/ archive/
git show 'af0073e5bd8a8799f0cfd322cfb27c8efd7b747d:archive/manifest.json'
git show 'af0073e5bd8a8799f0cfd322cfb27c8efd7b747d:archive/legacy-bugs.tar.gz' |
  tar -xzOf - 'bugs/review-2026-10-03/findings/CVAT-001/report.md'
```

For full recovery, extract the archived tree into a separate directory and verify
against the checkpoint manifest. Preserve the old
`bugs/review-2026-10-03/SHA256SUMS` as evidence: at consolidation 115 of its 128
entries matched, while 13 Python files already differed. The new manifest binds
the actually archived current bytes; it does not rewrite the old hash claims or
assert that current reproducers are identical to their original capture. A
historical reproducer's exit 0 meant it observed the old defect, not that current
behavior passed. Original implementation SHAs above remain distinct from the
checkpoint SHA that proves archive contents.

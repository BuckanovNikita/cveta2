# Managed datasets

A managed dataset is a named definition in the shared configuration file that combines
CVAT projects and S3 annotation CSVs into one versioned ClearML dataset. The
`cveta2 dataset` command group runs the workflow: `fetch` captures the source evidence
of every source into a new directory, the user transforms its `dataset.csv` with any
external script, `prepare` assigns stable train/val/test splits and validates the
transformed rows into a new preparation directory, `report-errors` opens CVAT review
issues for rejected rows traced to an original CVAT frame, and `publish` rechecks
everything and publishes exactly `dataset.csv`, `dataset.yaml` and `tasks.yaml`. The
same operations are prompt-free Python functions exported by `cveta2`: `list_datasets`,
`show_dataset`, `dataset_versions`, `fetch_dataset`, `prepare_managed_dataset`,
`compare_datasets`, `report_dataset_errors` and `publish_dataset`. Source evidence is
kept apart from the transformed training rows and travels inside the published
`tasks.yaml`, so the next fetch can reuse unchanged CVAT tasks.

Selecting and loading the personal and shared files, migration and policy writes are
described in [connection-and-configuration.md](connection-and-configuration.md). The
training validation and media checks that preparation runs are described in
[verification-and-bundles.md](verification-and-bundles.md); ClearML parent lookup,
version listing and the three-file upload are in
[clearml-publication.md](clearml-publication.md).

## Configuration

### Dataset definition

Each entry of the shared file's `datasets` mapping is one managed dataset. Its key is
the dataset name used by every operation. Unknown keys are rejected at every level.

| Field | Type and default | Meaning |
| --- | --- | --- |
| `sources` | list, at least one | Source definitions, below |
| `clearml.project` | nonempty string | Exact ClearML project; no recursive project matching |
| `clearml.dataset` | nonempty string | Exact ClearML dataset name |
| `api_url` | HTTP(S) URL | Class-registry API; user name or password in the URL is rejected |
| `s3_roots` | list of strings, `[]` | S3 image roots written to `dataset.yaml` and checked at prepare and publish |
| `empty_classes` | list of integers, `[]` | Registry class numbers marked `empty` in `dataset.yaml` |
| `splits` | mapping | Split policy, below |
| `overlaps` | mapping, `{}` | Overlap decisions keyed by image content SHA-256, below |

| Source field | Rule |
| --- | --- |
| `name` | Matches `[A-Za-z0-9][A-Za-z0-9_-]*` |
| `type` | `cvat` or `s3-csv` |
| `project` | Required for `cvat` and forbidden for `s3-csv`: a key of the shared `projects` mapping |
| `uri` | Required for `s3-csv` and forbidden for `cvat`: an exact `s3://bucket/key.csv` object |

An `s3-csv` URI must have scheme `s3`, a bucket without `@`, `:`, space or backslash, no
query or fragment, a key ending in `.csv` with no empty, `.` or `..` segment, and no NUL
character. A `cvat` source must have a `project` and no `uri`.

Any violation of the rules on this page fails loading with `Invalid shared project
configuration <path>; fields: <dotted field paths>`; the validator's own message (for
example `S3 source requires an exact s3://bucket/key.csv URI`, `CVAT source requires
only a project reference`, `Splits must sum to one with positive train and val` or
`Unknown shared project: <key>`) is kept as the chained cause.

Across the file:

- Source names are unique within a definition, and so are source references
  (type, project and URI); one reference under two names is rejected.
- `clearml` project/dataset pairs are unique across all definitions.
- Dataset keys and project keys match `[A-Za-z0-9][A-Za-z0-9_-]*`.
- A `cvat` source names a project key present in `projects`.
- A definition uses the single `cvat.host` and `cvat.organization` of its shared file.

`projects.<key>.id` gives the CVAT project ID of a `cvat` source, and the project's
`ignore` list excludes task IDs from that source. The other project fields belong to
ordinary fetch and images; see [connection-and-configuration.md](connection-and-configuration.md).

### Split policy

| Field | Default | Rule |
| --- | --- | --- |
| `train` | `0.6` | 0 to 1, must be positive |
| `val` | `0.2` | 0 to 1, must be positive |
| `test` | `0.2` | 0 to 1, may be 0 |
| `seed` | `42` | Integer |

The three fractions must sum to 1 within 1e-9.

### Overlap decisions

An `overlaps` key is the SHA-256 of an image's content. The value has `members`, the
exact set of source names that contribute that content, and `source`, the one source
whose rows are kept, or `null` to exclude every row of that content. See
[Overlapping content](#overlapping-content).

### Configuration hashes

Two order-free SHA-256 hashes bind fetched and prepared data to the configuration:

| Hash | Covers | Stored in |
| --- | --- | --- |
| Source-definition hash | `cvat.host` and `cvat.organization`; per source, sorted by name: `name`, `type`, the resolved CVAT project ID with its sorted ignored task IDs, and `uri` | `definition_hash` of `source-snapshot.yaml` and of the `managed` section of `tasks.yaml` |
| Definition hash | The source-definition hash plus `clearml`, `api_url`, `s3_roots` and `empty_classes` as sorted sets, `splits`, and `overlaps` with sorted members | `definition_hash` at the top of `preparation.json` and in the `managed` section of `dataset.yaml` |

Neither hash changes with list order, project keys, project `name`, `sync_root`,
`ignored_prefix`, `task_cache_s3`, or an ignored task's `name`, `description` and
`silent`. Entries for other datasets and projects not used by this definition do not
affect either hash.

| Edit after fetch | Result |
| --- | --- |
| Anything the source-definition hash covers | `prepare` and `publish` fail with `Source definition changed; fetch the managed dataset again` |
| `splits`, `overlaps`, `empty_classes`, `s3_roots`, `api_url` or `clearml` | The same fetch directory can be prepared again; an existing preparation fails `publish` with `Shared dataset policy changed; prepare again` |
| Bookkeeping fields and list order | No effect on fetch, preparation or publication, except that a project `name` change can change the approved local image roots, and `publish` then fails with `Personal image roots changed; prepare again` |

Editing `splits` is refused by `prepare` when the latest parent has managed metadata
(see [Splits](#splits)). Editing `clearml` or `api_url` can make `prepare` require a new
fetch when the latest parent or the class registry differs from the one recorded at
fetch time.

## Fetch

```bash
cveta2 dataset fetch construction --output-dir fetched [--refresh]
```

`fetch_dataset(name, *, output_dir, refresh=False, config_path=None,
project_config=None)` performs these steps:

1. Loads the definition; an unknown name fails with `Unknown managed dataset: <name>`.
2. Reads the class registry from `api_url`.
3. Looks up the latest finalized, nonarchived ClearML dataset with the exact destination
   project and name (the parent). When the destination project or dataset does not
   exist, the parent is `null` and nothing is created remotely. When a parent exists,
   fetch reads the `managed` section of its `tasks.yaml` as the previous snapshot. A
   parent without `tasks.yaml` or without that section has no previous snapshot.
4. Captures every source in definition order, then writes the output directory.

Any source failure aborts the whole fetch before any output is written.

### CVAT sources

For each `cvat` source, fetch lists the project's labels and tasks and the jobs of
each task, without reading annotations. A task is completed when its status is
`completed`, it has at least one job, and every job is at stage `acceptance` and state
`completed`. Tasks whose IDs are in the project's `ignore` list are skipped.

A task's previous evidence is reused, without reading its annotations, when all of the
following hold:

- the source has previous evidence under the same source name, of type `cvat`, with
  stored `labels`, for the same CVAT project ID, and with the same label fingerprint
  (any change to the project's labels, including attribute definitions, resets the
  source);
- the source is not reset (below);
- the task was completed in the previous evidence and is completed now, its
  `updated_date` is unchanged, and its previous evidence has tables.

Every other task is captured in full: frame metadata, annotations, jobs and issues are
read and assembled into rows as an ordinary fetch would. Capture fails with
`Task changed during fetch: <source>/<task>` or `CVAT task changed during capture:
<project>/<task>` when the task's `updated_date` moves while it is read, with
`CVAT task completion changed during capture: <task>` when its completion changes, and
with `CVAT returned task <task> outside project <project>` or `Duplicate task ids in
source <source>` for inconsistent listings. Tasks missing from the live listing drop out
of the evidence. A task that becomes unfinished is captured again and its rows move to
`in_progress.csv`.

Every source is reset, so all its tasks are captured again, when any of these holds:

- `refresh=True` (`--refresh`);
- there is no previous snapshot;
- the previous snapshot is legacy: it has no `registry`, or a `cvat` source without
  `labels`;
- the class-registry fingerprint differs from the previous one;
- the parent's `dataset.yaml` records the CVAT identity of the previous snapshot and it
  differs from the current `cvat.host` or `cvat.organization`;
- the parent's `dataset.yaml` records no CVAT identity, and the previous snapshot's
  source-definition hash differs from the current one.

Otherwise reuse is decided per source: a new or renamed source, or a `cvat` source with
another project ID, is captured in full while the other sources keep their reuse. A new
ignored task ID drops that task without reading anything; removing it again captures
only that task. A previous snapshot with a different source-definition hash is never an
error. A previous snapshot that is not legacy must carry `registry` and `labels`
matching their fingerprints, or fetch fails before reading any task (see
[Evidence completeness](#evidence-completeness)).

The source's four tables are rebuilt from all captured task rows of that source by the
ordinary partition rules in [fetch-and-partition.md](fetch-and-partition.md), so task
recency and deletion precedence are local to one source project, and rows superseded
inside a project stay in its `obsolete.csv`.

### S3 CSV sources

Each `s3-csv` source is downloaded in full on every fetch through the standard S3
credential chain; no image is downloaded. Any failure, including missing credentials,
profile or region, raises `ManagedError` `Cannot read required S3 CSV source: <uri>`.
The CSV must contain `image_name`, `image_path`, `instance_label`, `bbox_x_tl`,
`bbox_y_tl`, `bbox_x_br` and `bbox_y_br` (`S3 annotation CSV lacks required columns:
[...]`) and none of the provenance columns (`Source CSV contains reserved provenance
columns: [...]`). Values are not validated at fetch; `split` may be absent, and extra
columns are kept. The object's bytes become the source's `dataset.csv` (a UTF-8 BOM is
removed); its other three tables are header-only. The snapshot records the bytes'
SHA-256 as `content_hash` and the opaque `ETag` and `VersionId` when S3 returns them; a
changed object replaces the source's whole contribution. Images referenced by the CSV
must be readable locally before preparation.

### Combined rows and provenance

The output `dataset.csv` concatenates the `dataset.csv` table of every source in
definition order and appends five provenance columns:

| Column | CVAT source | S3 CSV source |
| --- | --- | --- |
| `source_id` | Source name | Source name |
| `source_project_id` | CVAT project ID | Empty |
| `source_task_id` | The row's `task_id` | Empty |
| `source_frame_id` | The row's `frame_id` | Empty |
| `source_row_id` | `<source name>:<sha256>:<n>` | `<source name>:<sha256>:<n>` |

The SHA-256 in `source_row_id` is taken over the row as JSON with sorted keys, including
the four preceding provenance columns; `n` counts earlier identical rows, starting at 0.
A source table that already holds any provenance column fails with `Source <name>
contains reserved fields: [...]`. S3 rows never receive task or frame IDs.

### Fetch directory

`output_dir` must not exist (`Candidate directory already exists: <dir>`). Its parent is
created when missing. All files are staged in a temporary directory beside it and
hard-linked into place, `source-snapshot.yaml` last; an OS failure raises
`Cannot export managed source candidate: <dir>`.

| Path | Content |
| --- | --- |
| `dataset.csv` | Combined rows with provenance columns |
| `sources/<source>/dataset.csv`, `obsolete.csv`, `in_progress.csv`, `deleted.csv` | The source's four tables; an S3 source fills only `dataset.csv` |
| `source-snapshot.yaml` | The managed snapshot, below |

### Fetch result

`fetch_dataset` returns, and the CLI prints as JSON:

| Key | Value |
| --- | --- |
| `directory` | `output_dir` as a string |
| `rows` | Row count of the combined `dataset.csv` |
| `parent_id` | Pinned parent dataset ID or `null` |
| `sources` | One entry per source: `name`, `fetched` and `reused` task IDs, `content_hash` (S3 only, otherwise `null`) |

## Managed snapshot

The snapshot is written to `source-snapshot.yaml` by fetch and embedded under the
`managed` key of `tasks.yaml` by preparation.

| Field | Content |
| --- | --- |
| `format_version` | `1` |
| `definition_hash` | Source-definition hash at fetch time |
| `registry_hash` | Fingerprint of the class registry |
| `registry` | Full registry records sorted by `number`, with keys `id`, `number`, `name`, `techClass`, `isPeriodical`, `isCritical`, `threshold` |
| `parent_id` | Parent pinned at fetch, or `null` |
| `sources` | Per-source evidence, below |
| `assignments` | Image content SHA-256 to `train`, `val` or `test` |
| `image_hashes` | Image path to content SHA-256 |

| Source field | Content |
| --- | --- |
| `name`, `type` | From the definition |
| `project_id` | CVAT project ID (`cvat`) |
| `tasks` | Task ID string to `id`, `updated_date`, `completed` and `tables` (the task's four CSV tables), including tasks with no rows |
| `labels_fingerprint`, `labels` | Fingerprint and full CVAT label definitions sorted by ID, with attributes, sublabels, type, SVG and identity fields (`cvat`) |
| `tables` | The source's four partitioned CSV tables |
| `uri`, `content_hash`, `etag`, `version_id` | S3 object identity (`s3-csv`) |
| `fetched`, `reused` | Task IDs captured or reused by this fetch |

At fetch, `assignments` and `image_hashes` are copied from the previous snapshot; the
registry and label fingerprints are SHA-256 over the records sorted by `number` or `id`.
An absent `registry` or `labels` field marks legacy evidence; an empty list is captured
evidence of an empty definition. `registry` and `labels` are omitted when absent.

### Evidence completeness

Preparation, publication and fetch reuse require complete evidence: `registry` present
and matching `registry_hash`, and every `cvat` source with `labels` matching
`labels_fingerprint`. Otherwise they fail with one of:

- `Source snapshot lacks class-registry records; fetch and prepare again`
- `Class-registry records do not match their fingerprint; fetch and prepare again`
- `Source snapshot lacks CVAT label definitions: <source>; fetch and prepare again`
- `CVAT label definitions do not match their fingerprint: <source>; fetch and prepare again`

A legacy snapshot in a published parent is still read: fetch resets every source and
keeps its `assignments`.

## Preparation

```bash
cveta2 dataset prepare construction transformed.csv --source fetched --output-dir prepared [--clean]
```

`prepare_managed_dataset(name, csv, *, source, output_dir, clean=False,
config_path=None, project_config=None)` accepts any transformed CSV; rows need not map
one-to-one to fetched rows, and cveta2 neither runs nor constrains the transformation.
`source` is the fetch directory (or its `source-snapshot.yaml`). It never prompts and
makes no remote change.

### Order of checks

1. Reads the class registry and the latest parent, as fetch does.
2. When the parent's `dataset.yaml` has a `managed` section whose `splits` differ from
   the current ones, fails with `Split policy changed; select a new dataset lineage`.
3. Reconciles classes (see [Classes](#classes)).
4. Reads the transformed CSV and `source-snapshot.yaml` once as bytes. `source` must not
   be a symlink (`Source directory must not be a symlink: <source>`) and both files must
   be regular non-symlink files (`Expected a regular nonsymlink file: <path>`); file read
   and snapshot schema failures raise `Cannot capture managed preparation inputs: ...`.
   The transformed CSV is parsed as described under "CSV reading" in
   [verification-and-bundles.md](verification-and-bundles.md), and its parse errors
   (such as `CSV must have unique, nonempty column names.`) are raised unwrapped.
   Source names in the snapshot must be unique, each source must have its four tables, and each
   task's tables must carry that task's ID.
5. Checks [evidence completeness](#evidence-completeness), then:
   - source-definition hash differs: `Source definition changed; fetch the managed dataset again`;
   - registry fingerprint differs: `Class registry changed; fetch the managed dataset again`;
   - latest parent differs from the snapshot's `parent_id`: `Source parent changed; fetch the managed dataset again`;
   - the parent has no `dataset.yaml`: `Parent <id> lacks dataset.yaml; choose a new dataset name`.
6. Requires a unique `image_path` column (`Upload CSV must have a unique image_path
   column`) whose every value is an absolute local path (`Upload image_path must be an
   absolute local path: <value>`) lying, after symlink resolution, under an approved
   local root (`Transformed images are outside approved roots: [...]`). Every nonempty
   `s3_image_path` value, when that column exists, must lie under at least one approved
   S3 root with all matching roots in one bucket, as described under "Roots" in
   [verification-and-bundles.md](verification-and-bundles.md) (`S3 image path is outside
   approved S3 roots: <value>`). Access to every configured S3 root is then checked.
7. Hashes each distinct readable `image_path` with SHA-256. An unreadable path gets the
   identity `unreadable:<sha256 of the path>`, so media validation reports it.
8. Resolves overlaps, assigns splits, validates and writes the preparation directory.

### Approved image roots

`dataset.yaml` `images.local_root` lists, without duplicates, the personal
`cache.images_root`, then for each `cvat` source, looked up under both the project key
and the project `name`, the personal `image_cache` entry and the effective
`cache.images_root` for that project (its per-project override, else the global value). `images.s3_root` is the definition's `s3_roots`.

### Classes

Classes are reconciled from the parent's `dataset.yaml` classes (or none) against the
current registry by registry `number`, which becomes `prod_id`. New numbers and
renamed classes are accepted without a decision; a rename keeps the old name in
`alt_names`. Each class's `empty` flag is set from `empty_classes`. Preparation fails
when a parent `prod_id` is missing from the registry (`Previous class prod_id values
missing from API: [...]`), when the registry repeats a number or a name, or when
`empty_classes` names a number absent from the registry (`Shared exclusion policy
contains unknown class identities`). How `empty` and unknown classes affect rows is
described in [verification-and-bundles.md](verification-and-bundles.md).

### Overlapping content

A missing `image_name` column fails with `Managed CSV lacks required columns:
['image_name']`; a missing, empty or relative `image_path` has already failed the root
check in step 6. A row with an empty `image_name` aborts preparation with `Invalid
image filename at row <n>`; it is not a cleanable finding. Rows are grouped by image
content hash.

- One `image_name` with two different contents fails with `Conflicting image filename
  for different content: <name>`.
- Content contributed by more than one `source_id` without a decision fails with
  `Image overlap requires source selection or exclusion: <digest>; sources=[...]`.
- With a decision, its `members` must equal the contributing source set (`Image overlap
  membership changed; review decision: <digest>`), every row of that content must have
  a `source_id` (`Image overlap contains unmapped rows: <digest>`), and `source` must be
  a member (`Image overlap selects an unknown source: <digest>`). Only rows of `source`
  are kept; with `source: null` all rows of that content are dropped.
- Rows without `source_id`, or content from a single source, pass unchanged.

After adding a decision, `prepare` can run again on the same fetch directory.

### Splits

Splits are assigned before validation. Any `split` column in the transformed CSV is
replaced; the report counts changed rows in `split_replacements`.

- Previous assignments start from the snapshot's `assignments`; the parent's
  `dataset.yaml` managed `assignments` (or, for a parent without a managed section, its
  carried splits) are applied on top and win for the same content hash. They are kept, including content absent from
  the current rows, so reintroduced content returns to its split.
- New content gets `train` when `x < train`, `val` when `x < train + val`, otherwise
  `test`, where `x` is the SHA-256 of `<seed>\x00<content hash>` read as an integer and
  divided by 2^256. Assignment is independent of row order, and all rows of one content
  share a split.
- Fractions are targets, not exact counts; existing assignments are never moved to
  rebalance them.
- Assignments of `unreadable:` identities are not stored.

When the parent has `dataset.yaml` without a managed section, its `dataset.csv` is
downloaded and its splits are carried for content it published under exactly one of
`train`, `val` or `test`. Only parent `image_path` values that resolve to existing files
under an approved local root are hashed; other parent paths are unresolved. The report
adds `parent_splits_carried` and
`parent_split_conflicts` (distinct content hashes) and `parent_split_unresolved`
(distinct parent paths without a usable hash).

### Validation and readiness

The split rows are validated with the `clearml-yolo` profile, image checks and the
training rules of [verification-and-bundles.md](verification-and-bundles.md). The
preparation is ready when there are no blockers, no structural errors, and either no
cleanup is required or `clean` is set. With `clean`, the payload holds the cleaned rows.

### Feedback findings

A row with an error-severity issue is mapped to an original CVAT frame only when all of
these hold: `source_id` names a `cvat` source of the snapshot; `source_task_id` and
`source_frame_id` are nonnegative integers; `source_project_id` is empty or equals the
source's project ID; and that source, project, task and frame occur in the task's
captured tables. Other rows with errors are counted in `unmapped_errors` and stay local;
S3 rows are never mapped.

Mapped reasons are grouped per frame into one finding with sorted unique `codes` and
`messages`. Its `marker` is `cveta2:verification:` followed by the SHA-256 of the JSON
array `[source, project, task, frame, codes]`.

### Task manifest

`tasks.yaml` `included` lists the task IDs of mapped rows in the accepted output.
`obsolete` lists task IDs that the obsolete-task rule of
[verification-and-bundles.md](verification-and-bundles.md) derives from each CVAT
source's tables, minus `included`. `managed` holds the snapshot with `assignments`
replaced by the new assignments and `image_hashes` by the hashes of readable images in
the accepted rows.

### Preparation directory

`output_dir` must not exist (`Preparation directory already exists: <dir>`) and must
not be inside the fetch directory (`Preparation must be outside the fetch source
directory: <dir>`). Files are staged beside it and hard-linked into place, with
`preparation.json` and `preparation.sha256` last; an OS failure raises `Cannot persist
managed preparation: <dir>`.

| File | Content |
| --- | --- |
| `transformed.csv` | Exact bytes of the transformed CSV |
| `source-snapshot.yaml` | Exact bytes of the fetch snapshot |
| `report.json` | Validation report, below |
| `broken-images.csv` | Input rows of images rejected by the image checks |
| `dataset.csv`, `dataset.yaml`, `tasks.yaml` | Payload, only when ready |
| `preparation.json` | Preparation record, below |
| `preparation.sha256` | SHA-256 of the `preparation.json` bytes |

`dataset.yaml` holds `api_url`, `classes`, `images` and a `managed` section with
`format_version` `1`, `name`, the definition hash as `definition_hash`, the full
`definition`, the `cvat` identity and `assignments`.

`preparation.json` fields:

| Field | Content |
| --- | --- |
| `format_version` | `2` |
| `name` | Dataset name |
| `definition_hash` | Definition hash |
| `parent_id`, `parent_version` | Parent at prepare time, or `null` |
| `registry_hash` | Registry fingerprint |
| `source_hash` | SHA-256 of the `source-snapshot.yaml` bytes |
| `input_hash` | SHA-256 of the `transformed.csv` bytes |
| `payload_hashes` | SHA-256 per payload file; empty when not ready |
| `image_hashes` | Readable accepted image paths to content SHA-256 |
| `snapshot` | The snapshot embedded in `tasks.yaml` |
| `findings` | Mapped findings: `source_id`, `project_id`, `task_id`, `frame_id`, `codes`, `messages`, `marker` |
| `ready`, `clean` | Readiness and the `clean` option |

`report.json` is the verification report of
[verification-and-bundles.md](verification-and-bundles.md) without `metadata_columns`,
plus `ready`, `blockers`, `broken_image_rows`, `mapped_findings`, `unmapped_errors`,
`split_replacements` and, when a parent without managed metadata was adopted, the three
`parent_split_*` counts.

`prepare_managed_dataset` returns `PreparationSummary` with `directory`, `ready` and
`report` (the `report.json` content).

## Loading a preparation

`report-errors` and `publish` load the preparation and fail when any binding is broken:

- the directory is a symlink or not a directory, or a file is not a regular non-symlink
  file;
- `preparation.sha256` does not match `preparation.json`: `Managed preparation record
  checksum mismatch; prepare again`;
- `transformed.csv` or `source-snapshot.yaml` does not match `input_hash` or
  `source_hash`: `Managed input or source snapshot changed; prepare again`;
- the record's snapshot, registry hash or parent differ from `source-snapshot.yaml`
  apart from `assignments` and `image_hashes`: `Managed source binding is inconsistent;
  prepare again`;
- the payload inventory is not exactly the three files when ready, or not empty when
  unready (`Invalid managed payload inventory; prepare again`), or a payload hash differs
  (`Managed payload checksum mismatch; prepare again`);
- `tasks.yaml` `managed` differs from the record's snapshot (`Managed task snapshot
  changed; prepare again`), or `dataset.yaml` lacks `managed` or has another definition
  hash (`Managed metadata binding changed; prepare again`).

Other read or schema failures raise `Cannot load managed preparation: <dir>: ...`.
`preparation.sha256` detects accidental edits, not deliberate rewriting.

## Freshness checks

Before delivering feedback and before publishing, the preparation is checked against
the current state, in this order:

1. Evidence completeness of the record's snapshot.
2. Source-definition hash: `Source definition changed; fetch the managed dataset again`.
3. Definition hash: `Shared dataset policy changed; prepare again`.
4. Latest parent ID: `Latest ClearML parent changed; fetch and prepare again`; parent
   version: `ClearML parent version changed; prepare again`; parent without
   `dataset.yaml`: `Parent <id> lacks dataset.yaml; choose a new dataset name`.
5. Registry fingerprint: `Class registry changed; fetch and prepare again`.
6. Pending feedback receipts are reconciled (see [Feedback](#feedback)).
7. Sources, using task times adjusted by acknowledged feedback:
   - an S3 object whose content hash changed: `S3 source changed; fetch again: <source>`;
   - a CVAT project no longer in `projects`: `Managed CVAT project no longer configured`;
   - a changed label fingerprint or set of nonignored tasks: `CVAT source changed; fetch
     again: <source>`;
   - a task whose `updated_date` or completion changed: `CVAT task changed; fetch again:
     <source>/<task>`.
   Only task metadata and labels are read; annotations are not downloaded.
8. Media, only for a ready preparation: the current approved local roots must equal the
   recorded ones (`Personal image roots changed; prepare again`); roots and coverage are
   checked again; the hashes of readable images must equal `image_hashes` (`Prepared
   images changed; prepare again`); the payload must pass validation without cleanup
   (`Prepared payload no longer passes training validation`).

## Feedback

```bash
cveta2 dataset report-errors prepared
```

`report_dataset_errors(prepared, *, config_path=None, project_config=None)` runs the
freshness checks, then delivers every finding as a CVAT issue, and returns
`FeedbackOutcome` with `created`, `existing`, `unmapped` (the report's
`unmapped_errors`) and `failed` (strings `<source>/<task>/<frame>: <error>`). It works
on unready preparations. A failure of one finding is recorded in `failed` and the
others continue.

### Issue

The issue is created on the single `annotation`-type job whose frame range contains the
frame (`Feedback frame has no unique annotation job` otherwise), at position `[0, 0]`
of that frame, with the message:

```text
[cveta2:verification:<64 hex>]
cveta2 dataset verification: <code>, <code>
<message>
...
```

A finding counts as delivered when an issue on its frame has a comment containing the
bracketed marker. Delivery writes only issues; annotations, labels and job states are
never changed. The task must still belong to the finding's project and the frame must
lie inside the task.

### Ledger

Receipts are stored at `managed-feedback/<source_hash>.json` beside the selected personal
configuration file, so all preparations made from the same `source-snapshot.yaml` bytes
share delivery history. The file is replaced atomically; a symlink, a duplicate JSON
key, an unreadable file or an index key that differs from its receipt's `marker` fails
closed. A preparation's own `feedback.json` is read too: its receipts missing from the
shared ledger are copied there and the file is left unchanged.

| Ledger field | Content |
| --- | --- |
| `format_version` | `1` |
| `receipts` | Marker to `source_id`, `project_id`, `task_id`, `frame_id`, `marker`, `before_date`, `fingerprint`, `after_date`, `delivered` |

The fingerprint is a SHA-256 over the task (without `updated_date`), its frame metadata,
annotation shapes, jobs and the project's labels; issues are excluded, so feedback
alone never looks like an annotation change.

### Delivery per finding

1. Read the task state. A receipt that exists must match the finding's source, project,
   task, frame and marker (`Feedback marker belongs to different source evidence`) and
   fingerprint (`Source annotations changed during feedback: <task>`).
2. A delivered receipt whose issue disappeared fails with `Previously acknowledged CVAT
   issue disappeared; prepare again`; otherwise it counts as existing.
3. A pending receipt whose task time moved is accepted only when the marker is now
   present or the task's acknowledged chain in the ledger (successive `before_date` to
   `after_date` of delivered receipts on the same source, project and task, with the
   same fingerprint) ends at the current time; otherwise it fails with `Unacknowledged
   task change during feedback: <task>`.
4. If the marker is already present, the receipt is completed and the finding counts as
   existing.
5. Otherwise the intent is written to the ledger before the issue is created (failure
   to persist it raises `Cannot persist required feedback checkpoint` and prevents the
   write). A new receipt is refused when another receipt on the same task has a
   different fingerprint. After the write, the task facts must be unchanged (`Source
   annotations changed while reporting task <task>`) and the marker present (`Created
   CVAT issue was not confirmed for task <task>`); then the receipt records the new
   task time as `after_date` and the finding counts as created.

In step 6 of the freshness checks, pending receipts are reconciled by reads only: a
receipt whose fingerprint still matches and whose marker is present is completed; a
changed fingerprint fails with `Source annotations changed during feedback: <task>`.

The published `tasks.yaml` keeps the task times from before feedback, so the next fetch
captures a task again when its own issue moved its time.

## Publication

```bash
cveta2 dataset publish prepared
```

`publish_dataset(prepared, *, config_path=None, project_config=None)`:

1. Fails with `Preparation is not ready; review diagnostics and accept cleanup` unless
   the record is ready and the payload is exactly the three files.
2. Runs the freshness checks.
3. Delivers all findings; any failure stops publication with `CVAT feedback delivery
   failed; retry report-errors before publication`.
4. Checks the sources again with acknowledged feedback times, and the latest parent ID
   again (`ClearML parent changed during feedback; prepare again`).
5. Copies the captured payload bytes to a private temporary directory and publishes
   them as a child of the recorded parent, or as a version without parent when there is
   none; see [clearml-publication.md](clearml-publication.md).

It returns `Publication` with `dataset_id` and `version`. Images, reports, the
preparation record and the ledger are never published.

## Other operations

| Operation | API | Result |
| --- | --- | --- |
| `list` | `list_datasets()` | List of definitions sorted by name, each with `name` and the definition's fields; no network access |
| `show NAME` | `show_dataset(name)` | `name`, `definition`, `parent_id`, `parent_version` of the latest parent |
| `versions NAME` | `dataset_versions(name)` | Finalized, nonarchived versions of the exact destination: `id`, `project`, `name`, `version`, `created` |
| `diff OLD NEW` | `compare_datasets(old, new)` | Comparison, below |

All functions take keyword-only `config_path` and `project_config` (`Path | None`) and
fail without an attached shared file, `diff` included. Each reference of `diff` is a
directory (its `dataset.csv` is read), a CSV file, or, when no such local path exists, a
ClearML dataset ID whose `dataset.csv` is downloaded from that exact finalized version.

| Key | Content |
| --- | --- |
| `rows` | `old`, `new`, and multiset counts `added`, `removed`, `unchanged` over all columns, independent of column order |
| `images` | Sorted `added`, `removed`, and `changed` image names (rows differ); grouped by `image_name`, else `image_path` |
| `classes` | Sorted `added` and `removed` nonempty `instance_label` values |
| `splits` | `old` and `new` unique image counts per split |

`None`, NA and NaN cells compare as one missing value; an unsupported cell type fails
with `Unsupported comparison cell type: <type>`.

## CLI

Every operation accepts `--config` (personal file), `--project-config` (shared file) and
`--json`. Mapping parameters have no override flags. `show`, `versions`, `fetch` and
`prepare` take the dataset name; `fetch` and `prepare` require `--output-dir`.

Each operation prints its result as indented JSON with non-ASCII characters kept; the
`--json` flag does not change the output. Exit codes:

| Code | When |
| --- | --- |
| `0` | Success |
| `1` | `prepare` finished and the preparation is not ready |
| `2` | `report-errors` returned failed deliveries, or any `Cveta2Error`, Pydantic validation error or OS error |

Errors are logged as `Ошибка операции с набором данных: <error>` without a traceback.

## Limits

- No image is downloaded or published; S3 CSV images must already be local.
- Transformation is external and untraced; rows without provable CVAT lineage are
  never reported to CVAT.
- Split fractions are targets only, and a split policy cannot change for a lineage
  whose parent has managed metadata; use a new dataset name.
- A parent without `dataset.yaml` blocks preparation and publication; use a new dataset
  name.
- Feedback issues are frame-level at position `[0, 0]`, not at the rejected box.
- There is no transaction with CVAT or S3: a source change after the last freshness
  check is not detected.

## Code and tests

- [`domain/managed/`](../../cveta2/domain/managed/) — definitions, hashes, snapshot,
  split, overlap and comparison policies, preparation records
- [`application/use_cases/managed_sources.py`](../../cveta2/application/use_cases/managed_sources.py),
  [`managed_preparation.py`](../../cveta2/application/use_cases/managed_preparation.py),
  [`managed_publication.py`](../../cveta2/application/use_cases/managed_publication.py),
  [`managed_feedback.py`](../../cveta2/application/use_cases/managed_feedback.py) — workflows
- [`adapters/cvat/managed_sources.py`](../../cveta2/adapters/cvat/managed_sources.py),
  [`adapters/cvat/managed_feedback.py`](../../cveta2/adapters/cvat/managed_feedback.py),
  [`adapters/s3/managed_sources.py`](../../cveta2/adapters/s3/managed_sources.py),
  [`adapters/clearml/managed_sources.py`](../../cveta2/adapters/clearml/managed_sources.py),
  [`adapters/files/managed_sources.py`](../../cveta2/adapters/files/managed_sources.py),
  [`adapters/files/managed_preparation.py`](../../cveta2/adapters/files/managed_preparation.py),
  [`adapters/files/managed_feedback.py`](../../cveta2/adapters/files/managed_feedback.py) — effects
- [`composition/managed.py`](../../cveta2/composition/managed.py),
  [`interfaces/managed_datasets.py`](../../cveta2/interfaces/managed_datasets.py),
  [`interfaces/commands/managed.py`](../../cveta2/interfaces/commands/managed.py) — wiring, API, CLI
- Tests: [`test_managed_models.py`](../../tests/test_managed_models.py),
  [`test_managed_policies.py`](../../tests/test_managed_policies.py),
  [`test_managed_sources.py`](../../tests/test_managed_sources.py),
  [`test_managed_preparation.py`](../../tests/test_managed_preparation.py),
  [`test_managed_feedback.py`](../../tests/test_managed_feedback.py),
  [`test_managed_workflow.py`](../../tests/test_managed_workflow.py),
  [`test_managed_cli.py`](../../tests/test_managed_cli.py)
- The unit suite replaces CVAT, S3 and ClearML with fakes; behavior against live
  services is established only by the live tests.

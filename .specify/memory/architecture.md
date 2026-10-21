# cveta2 architecture

The layer diagram and its rule live in [engineering.md](engineering.md).
This living Spec Kit context maps module ownership, command flows, and behavior
constraints for future feature plans. [CONTRIBUTING.md](../../CONTRIBUTING.md)
covers the same ground in Russian, at overview depth.

## Module organization

Canonical implementation lives in five packages. Supported top-level modules
remain compatibility facades; canonical packages never import those facades.

- **`cveta2/domain/`** - Pure policies and neutral values:
  - `models.py` - Pydantic annotation/project/task models, including optional box confidence.
  - `errors.py` - `Cveta2Error` and public subclasses; interfaces map these to clean exits.
  - `partition.py` - Dataset/obsolete/in-progress partitioning, task-ID recency and deletion precedence.
  - `merge.py` - In-memory merge, split propagation and task-ID conflict resolution.
  - `conversion.py` - Pixel/YOLO/COCO boxes, coordinate transforms, row validation,
    label parsing, class-name normalization, CSV row builders and output formatting.
  - `baseline.py` - Whats-new cutoff and completed-task identity across supplied frames.
  - `output.py` - UTF-8 CSV settings, text-column schema and count/preview formatting.
  - `paths.py` - Pure frame/key/filename identity, containment components and duplicate-choice rules.
  - `cache.py` / `storage.py` / `upload.py` - Cache schema, cloud-storage/transfer
    values and pure upload validation/fingerprinting/recovery comparisons.
- **`cveta2/application/ports/`** - Application-owned typed contracts and neutral DTOs:
  - `cvat.py`, `dtos.py`, `client.py` - `CvatApiPort`, frozen raw CVAT dataclasses,
    resolved client values and session factory.
  - `cache.py` - Cache reads/writes, pruning and strict invalidation, including local-only invalidation.
  - `images.py` / `storage.py` - Image download/sync and upload/server mapping with typed outcomes.
  - `dataset.py` / `conversion.py` / `workflow_files.py` - Narrow CSV, path
    enrichment, image discovery/dimensions/materialization and owned-output lifecycle operations.
  - `manifests.py` - Recovery-record persistence.
  - `execution.py` - Ordered bounded execution with explicit worker and exception policies.
- **`cveta2/application/settings.py` / `results.py`** - Validated settings and
  neutral results without configuration loading or environment discovery.
- **`cveta2/application/client/`** - SDK-free `ApplicationClient` built from explicit ports:
  - `base.py` / `context.py` - API/session lifecycle and already-resolved settings.
  - `read.py` / `fetch.py` - Project/task lookup and per-task fetch pipelines.
  - `write.py` / `task_ops.py` - Task creation, annotation/issue upload, label patches,
    deletion/drop-label/status operations.
  - `images.py` - Image operations over the supplied image port.
  - `session.py` - `TaskWriteSession`, memoizing one metadata read per task.
  - `shared.py` - `FetchContext` and 5xx skip policy.
  - `assembly.py` / `extractors.py` - Fetch row assembly and rectangle/polygon extraction.
  - `mapping.py` - Frame lookup and annotation metadata mapping.
  - `upload_mapping.py` - Pure shape/issue DTO construction and existing-issue matching;
    `session.py` supplies memoized task facts and `write.py` owns port calls.
- **`cveta2/application/use_cases/`** - Prompt-free orchestration; raises `Cveta2Error`:
  - `fetch.py` - `fetch_project()` / `fetch_selected_tasks()`, cache use, promotion
    barrier, partitioning and local output ordering.
  - `upload/` - `types.py` defines upload requests/results; `planning.py` selects
    frames/labels; `staging.py` resolves images and validates labels; `recovery.py`
    owns manifest transitions and task/shape verification; `orchestration.py`
    sequences effects through supplied ports. The package preserves existing exports.
    Domain upload policy owns the shared annotation-row mask and bbox-column order.
  - `convert/{common,yolo,coco}.py` - Conversion preparation, dimension caching
    and YOLO/COCO orchestration over supplied file ports and search-directory values.
  - `merge.py` / `whats_new.py` - Dataset merge and baseline orchestration over persistence ports.
  - `resolve.py` - `ORG/PROJECT` parsing, organization switching and project-from-task inference.
  - `task_ops.py` - Task-operation orchestration and supplied invalidation.
- **`cveta2/adapters/`** - Outgoing effects:
  - `cvat/{sdk_adapter,sdk_requests,sdk_convert,connection,transport,storage}.py` - CVAT SDK
    client construction, requests, opaque SDK objects to DTOs, cloud-storage values
    and translation to `CvatApiError`. `transport.py` owns context-local timeouts
    and the explicit read, non-idempotent-write and idempotent-write decorators;
    endpoint methods select one policy without changing wrapper order. All
    `cvat_sdk` imports stay here.
  - `s3/{download,upload,images,task_cache,types,utils,diagnostics}.py` - Boto3/S3
    construction, key probing/listing, upload/download/sync, shared annotation-cache
    mirrors, per-object transfer/retry outcomes and credential diagnostics.
    `boto3`/`botocore` imports stay inside `adapters/s3/`.
  - `config/{settings,projects_cache}.py` - YAML/environment/preset loading and
    organization-keyed metadata cache (`organizations: [{slug, name, projects}]`;
    empty slug is the personal workspace).
  - `files/{dataset,conversion,materialization,task_output,image_search,manifests,shared}.py`
    - Local CSV/text reads/writes, path resolution/confinement, dimensions,
    reflink/link/copy and export cleanup, per-task debug output, image discovery,
    atomic recovery records and shared-cache permissions.
  - `execution/{concurrency,retry}.py` - Thread fan-out, context-local `Workers`
    propagation, retry attempts/backoff/logging. Retry predicates remain beside
    protected calls in the CVAT/S3 adapters.
  - `clearml/bundle.py` - Optional exact-parent lookup and explicit three-file
    child publication and ClearML StorageManager S3-root access; SDK errors retain
    a known child ID and never imply finalization.
  - `class_api/` - Public HTTP class-registry reads and validated class identities.
  - `files/{verification,media,bundle,bundle_paths}.py` - Lexical CSV and diagnostics,
    canonical media inspection, independent local-root containment, source/payload
    snapshots, strict metadata and staging. S3 root access for bundle publication
    is injected through its own port and owned by the ClearML SDK adapter.
- **`cveta2/composition/`** - Production dependency construction:
  - `client.py` - Supported `CvatClient` facade around `ApplicationClient`,
    resolved configuration, production session/image/execution adapters and
    invocation-time worker/failure policies.
  - `workflows.py` / `conversion.py` - Resolve workflow settings/search roots and
    inject cache, storage, files, manifests, clocks, locks and runners.
  - `configuration.py` / `files.py` / `runtime.py` / `diagnostics.py` - Incoming
    access to configuration/files, network worker/timeout setup and diagnostics.
  - `verification.py` / `dataset_bundle.py` - Construct verification and explicit
    preparation/publication effects; automatic fetch publication is removed.
- **`cveta2/interfaces/`** - Incoming adapters:
  - `cli.py` - Late-bound command registry, dispatch and error/exit boundary.
    Each command module configures its own parser; `commands/_parsers.py`
    holds shared project/config/list argument declarations.
  - `commands/` - Thin per-command adapters for fetch, upload, conversion,
    merge, labels, S3 sync, setup, ignore, task operations, whats-new and doctor.
    They own argument mapping, prompts and `sys.exit`.
  - `commands/_bootstrap.py` - `open_client()`: single configuration load, host
    check and timeout setup; credentials are prompted only at this boundary.
  - `commands/interactive/` - Project/task pickers, credentials, wizards,
    confirmations, questionary primitives/history. Other command helpers live in `_helpers.py`.
  - `api/` - `types.py` holds public connection/result values; `connection.py`
    owns context lifetime; `fetch.py`, `upload.py`, `projects.py` and `task_ops.py`
    map prompt-free workflow calls. The package re-exports public symbols with
    their original module identities for serialization and introspection.
    Interactive-only setup/setup-cache/doctor have no API counterpart.
    Missing settings raise `MissingHostError` / `MissingCredentialsError`.
- **Public top-level facades** - `api.py`, `cli.py`, `client.py`, `config.py`,
  `exceptions.py`, `models.py`, `dataset_partition.py`, `task_cache.py`,
  `image_downloader.py`, `image_uploader.py`, `s3_types.py`, `s3_utils.py`,
  `fs_utils.py`, `projects_cache.py` and `upload_manifest.py` retain supported
  imports, signatures and model/exception identities. `__init__.py` exposes public
  names lazily; `__main__.py` delegates execution to the CLI.
  Unsupported former `services/`, `commands/`, `_client/`, `_client_ops/` and
  `_clearml/` packages are removed; repository callers use canonical owners.
- **`cveta2/presets/`** - Bundled configuration resource; `default.yaml` keeps its existing location.

## Dependency and effect ownership

Source dependencies point inward: interfaces use composition and inner layers;
composition constructs adapters; adapters implement application-owned contracts;
application orchestrates contracts and domain values; domain depends only on
domain. Application use cases depend on the client and ports, while neutral
settings/results cannot depend on orchestration. CVAT/S3/config/ClearML adapter
groups remain independent and may use shared file/execution adapters. Internal
package siblings must remain acyclic. Canonical packages cannot import public
facades or the public root.

Domain/application may use lexical paths, in-memory pandas, Pydantic and Loguru.
Filesystem and pandas IO, configuration/environment discovery, SDK/network IO,
clocks, prompts and thread/process execution belong to adapters/composition or
incoming interfaces as appropriate. Dependencies and resolved settings are
passed explicitly; no global service locator supplies effects. Port protocols
must not import concrete implementations. Package initializers do not eagerly
load infrastructure when importing inner contracts.

`CvatClient(cfg=None, client_factory=None, *, api=None)` preserves lazy credential
checks when entering its owned session. Supplied APIs/sessions retain caller
ownership; owned sessions close deterministically. `ApplicationClient` receives
resolved settings, image/execution ports and an optional session factory/API
without reading configuration or constructing production clients.

`ConcurrentRunner` receives the ordered items, work function, worker limit and
caught exception types. Outcomes retain input order. Caught per-item failures
remain explicit outcomes; uncaught failures cancel queued work and join active
work before propagation. Composition supplies the concrete runner and worker
values; application never starts threads directly. Fetch receives its clock and
lock factory explicitly. Promotion joins every worker before fresh metadata,
normal fetching or output writes.

`DatasetFiles`/`ConversionFiles` expose workflow operations, including reading
validated CSVs, optional baseline siblings, imported-row writes, image dimensions,
materialization and output ownership/preparation/pruning. File adapters retain
UTF-8/newline handling, symlink containment, collision checks and cleanup. Domain
owns coordinate/label/schema validation and output formatting; configured image
search directories arrive as values. Upload checkpoints use `ManifestStore`;
completion is persisted before cleanup. Cache invalidation remains available
with cache reads disabled and then uses local-only effects.

Run `uv run lint-imports`, `uv run python scripts/check_architecture.py` and
`uv run pytest tests/test_architecture.py` after changing boundaries. The
import contracts cover exhaustive module classification, inward layers, adapter
independence, canonical facade exclusion, SDK/prompt ownership and internal
acyclicity, including local and type-only imports. AST acceptance checks reject
inner effect imports/calls (including aliases) and representative negative
fixtures exercise each boundary. Follow the feature's architecture acceptance
record to reconcile affected modules, actual changes, executed checks and review.

## Key data flow

1. **Fetch**: `interfaces/cli.py`/`interfaces/api/` → `composition/workflows.py` → `application/use_cases/fetch.py:fetch_project()` → `ApplicationClient.fetch_one_task()` per task → `adapters/cvat/sdk_adapter.py` → CVAT API
   - Opt-in `--skip-validation` / keyword-only `api.fetch(..., skip_validation=False)` runs an application promotion barrier before normal task selection. Every non-ignored project task is inspected using its full, nonempty job list, irrespective of job type or frame coverage. Only tasks whose jobs are all annotation/completed or acceptance/completed qualify; only annotation/completed jobs are updated in CVAT to acceptance/completed. Fully accepted tasks need no writes. Tasks run under the explicitly supplied CVAT worker limit, with sequential updates inside each task; all workers finish before fresh metadata and `completed_only` selection.
   - Promotion strictly invalidates each affected task's configured local cache and enabled S3 mirror before its first update, using the fetch config path and per-project `tasks_root` / `task_cache_s3`. Local invalidation still applies with caching disabled; S3 is not contacted in that mode. Read, invalidation or update errors abort before annotation fetching, image downloads, CSV writing. Successful CVAT writes persist without rollback; retry rechecks jobs and skips accepted ones. `fetch-task` / `api.fetch_task` have no promotion option.
   - Task selection scales with the request, not the project: `application/client/fetch.py:_select_tasks_for_fetch` retrieves each selector through `get_task` when all of them are numeric ids, and only walks the project task list otherwise — for a name selector, an id that turns out to name a task, a task belonging to another project, or an ignored id (all of which the listing path still owns, and all of which end in an error or a skip)
   - Completed tasks are served from `adapters/s3/task_cache.py` when an entry exists and its cached `task_updated_date` matches CVAT (local `~/.cache/cveta2/task_annotations/`, backfilled from the project bucket's `<prefix>/.cveta2_cache/`). Incomplete issue reads are not cached. A task or project-label edit invalidates the rendered payload; a job moved back to annotation also makes it ineligible. `--no-cache` / `--force` / `CVETA2_DISABLE_CACHE=true` override, full fetch prunes orphaned local entries
   - Returns `ProjectAnnotations(annotations, deleted_images)`
   - Annotations converted to `BBoxAnnotation` by `application/client/extractors.py`: standalone
     rectangles retain their existing mapping; polygons use all vertex extrema
     for tight axis-aligned bounds without rounding or clipping, with zero rotation.
     The shared mapping preserves annotation metadata and frame issues. Each
     converted polygon warns with task/annotation identity about approximation;
     malformed polygons (fewer than three pairs, odd count, nonfinite coordinates,
     zero-width/height bounds) warn individually and in a per-task skip summary.
     Cache schema 5 invalidates earlier local/S3 payloads that discarded polygons;
     cache hits retain existing logging and do not replay parsing warnings.
   - Result partitioned by `domain/partition.py` into dataset/obsolete/in_progress CSV files

2. **Upload**: `interfaces/commands/upload.py` (or `interfaces/api/`) → `composition/workflows.py` → `application/use_cases/upload/orchestration.py:upload_dataset()` → `ApplicationClient.create_upload_task()` + `ApplicationClient.upload_task_annotations()`
   - A manifest is written to `~/.cache/cveta2/uploads/<host-hash>/project_<id>/<fingerprint>.json` before CVAT is touched, and the task id recorded the instant it exists — `create_upload_task` splits the CVAT call in two (`create_task`, then `attach_task_data`) so there is a checkpoint between them. Completion is recorded before cleanup; an unlink failure warns with the successful task and retains safe recovery bookkeeping. Schema v3 binds the normalized host and full upload intent; legacy manifests without that identity cannot authorize resume.
   - `--resume` validates the manifest's server/project identity and the task's project ownership, then asks CVAT what that task actually holds: frame mapping and complete normalized annotation content decide verified reuse or refusal (`put_task_shapes` appends, so partial or conflicting content must never be appended again), and issues are matched individually by `(frame, initial message, bbox)` with coordinate tolerance. `set_deleted_frames` and `update_job` are idempotent and simply redone.
   - Validates labelled bounding boxes and full recovery identity before external writes. Mandatory initial/create/task-ID checkpoints fail closed before the next CVAT write. Replacement of a confirmed missing task clears the old ID before recording a pending create, so a lost replacement reply cannot authorize another create. A 503 never authorizes replay of non-idempotent create/append operations, even with `Retry-After`; unknown create outcomes require operator reconciliation. The motivating post-write failure was simulated, not observed on the live stand.
   - Reads CSV, uploads images to S3 (into `YYYY-MM/` subfolders), creates CVAT task, uploads annotations
   - Label selection is frame-based: a selected label pulls in all annotations of its frames (co-occurring labels included and validated against project labels); `--labels all` selects every dataset label plus unannotated frames (a literal dataset label named `all` wins over the shortcut)
   - Rows with `issue_state="new"` and non-empty `issue_text` become open CVAT issues **attached to the row's bbox**; rows with issue text but no complete bbox are skipped with a warning (no full-frame issues)
   - A CSV whose rows are all `instance_shape="deleted"` is a valid upload: the label step is skipped and only deleted frames are pushed

3. **Convert**: `interfaces/commands/convert.py` (or `interfaces/api/`) → `composition/conversion.py` → `application/use_cases/convert/`: `convert_to_yolo` exports CSV to YOLO format (images + labels), `convert_from_yolo` imports YOLO predictions back to CSV, `convert_to_coco` exports COCO detection format. Uses `PixelBox`/`YoloBox` NamedTuples for coordinate conversion.

4. **Partition Logic** (`domain/partition.py`):
   - For each image, finds **latest task** by `task_id` (comparing annotations + deletions). Ids are monotone with task creation and never move; `task_updated_date` does — a project label edit rewrites it on every task at once
   - If latest task is deletion → image goes to `obsolete`, added to `deleted_images`
   - Otherwise: completed tasks → `dataset` (latest) or `obsolete` (stale), non-completed → `in_progress`
   - **Completed** is recorded as `task_completed`, computed from every job at `acceptance`/`completed`, including Ground Truth/replica jobs and jobs without exported frames. `job_stage`/`job_state` describe regular annotation jobs, preferring unfinished positions in overlaps. `completed_task_ids()` uses the explicit task result and falls back to per-row job columns for legacy CSVs.
   - Deletion records are concatenated **before** annotation records to win same-task ties; see [Deleted images handling](#deleted-images-handling)

## Project specs and organizations

- Every project spec (CLI `-p`, API `project=`) accepts an id, a name, or `ORG/PROJECT` (`/PROJECT` = personal workspace). The org prefix calls `client.set_organization()`, switching the session org for all subsequent CVAT calls (`application/use_cases/resolve.py:split_project_spec` / `apply_project_org`).
- The interactive picker (`interfaces/commands/interactive/entities.py:select_project`) pages projects by organization — first page is the config org — and switches the session org on selection. Echoed re-run commands qualify `-p` via `_helpers.project_cli_spec` when the session org differs from the config default.
- `fetch-task` / `api.fetch_task` infer the project from the first numeric task id when no project is given (`application/use_cases/resolve.py:infer_project_from_tasks` via the `get_task` port method); name-only task specs still need an explicit project.
- A numeric project spec is named from the local projects cache when it holds the id, otherwise through the `get_project` port method, never by listing the organization; an id nobody owns falls back to the id as the display name (`application/use_cases/resolve.py:_project_display_name`). An ambiguous scoped name is rejected with candidate IDs before mutation; numeric ID selection is unchanged. A unique name spec resolves to CVAT's own spelling of the name (`find_project_by_name`, case-insensitive), so config sections keyed by project name match however the user typed it. `client.detect_project_cloud_storage` is memoized per project for the client's lifetime and dropped on `set_organization`.

## Deleted images handling

CVAT allows frames to be marked as deleted (`data_meta.deleted_frames`), but annotation shapes for those frames **still exist** in the task data. This is handled in two places:

1. **Collection** (`application/client/extractors.py`): Shapes are collected for ALL frames including deleted ones (needed for label counting, etc.)
2. **Partition** (`domain/partition.py`): Deletion records are placed FIRST in the concat, so the `sort_values` + `drop_duplicates(keep="first")` in `_latest_row_per_image` picks them in case of ties

Two different tasks can no longer tie, so the only tie left is inside one task: a frame it annotated and also marked deleted. That is the case the concat order settles (see `test_deleted_image_with_annotations_in_same_task`, and `test_deletion_wins_tie_in_a_frame_too_large_for_a_stable_sort` for why the row position is an explicit sort key rather than assumed sort stability).

## Nested frame names

Nested CVAT frame names (`sub/img.jpg`) keep `image_name` as a basename; the
full key is carried in the internal `frame_path` model field — kept in the task
cache JSON, excluded from the CSV — and used to build `s3_image_path`. The
local image cache mirrors the S3 key layout below the effective storage prefix
(`sync_roots` overrides the prefix, `cache.projects.<name>.ignored_prefix`
skips less of the hierarchy); see README.md for the user-facing description.
Frame names are a supported-data contract: POSIX-relative to the configured
storage root. Distinct images must have unique basenames and unique stems
(filenames without the final extension) across the project or dataset,
including all directories and splits: neither `dir1/xxx.jpg` and
`dir2/xxx.jpg` nor `xx.jpg` and `xx.png` are supported together. The same image
may still appear in multiple tasks or annotation rows. CSV identity uses the
basename, while YOLO label filenames use the stem; uniqueness is an input
requirement, not a guarantee of automatic validation. Absolute names below
the storage root are normalized to relative names; traversal and outside-root
names are rejected.

CVAT tracks are intentionally outside the extraction model. The SDK adapter
warns with the task id and count whenever it ignores tracks. Standalone shapes
reach `RawAnnotations`; the extractor accepts rectangles and polygons and warns
when skipping other shape types. Both fetch paths share this extraction behavior.

## Task-by-task processing

`fetch` reads one task at a time (`fetch_one_task()`), but the tasks themselves
run concurrently through the supplied `ConcurrentRunner` with the resolved CVAT worker limit; results
are merged positionally so the output does not depend on completion order.

The file port writes each task's rows to `output/.tasks/task_{id}.csv` as they arrive.
That directory is **removed after the merge** unless `--save-tasks` is given, and
nothing ever reads it back — it is a debugging artefact, not a resume point. The
only `--resume` in the project belongs to `upload`, and it reads its manifest
from `~/.cache/cveta2/uploads/`, not from here.

## Remediation contracts

Conversion validates every split before writing; repeated export refreshes image bytes. COCO replacement removes only metadata-owned obsolete output after validating ownership paths, preserving unrelated files. Malformed CSV/YAML becomes contextual domain errors; malformed YOLO lines are skipped with file/line warnings while valid siblings survive.

S3 sync preflights the complete source-to-destination map and rejects noncanonical keys and collisions before writing. Cache hits require regular files; directories are never removed automatically. Unusable read-only annotation caches degrade to uncached reads with warnings. Boto3 upload wrapper failures participate in per-object accounting.

Derived project cache paths encode unsafe components and enforce containment without changing logical names. Configuration rejects negative/nonfinite data timeouts; the CLI catches typed validation errors. Credential hints retain the selected config source. Stored ignore IDs can be removed without remote task lookup. Doctor requires valid CVAT settings, treats S3/cache diagnostics as advisory, and returns 1 only for failed or unavailable required checks.

## Explicit verification and reviewed publication

`domain/verification/` owns schema, geometry, positional findings, whole-image
quarantine and proposed cleanup. `domain/bundle/` owns API number/prod_id identity,
class aliases/empty decisions, task supersession, training constraints and local
preparation records. Both consume facts without filesystem/network/SDK effects.

`application/ports/verification.py` and `dataset_bundle.py` define external reads,
media inspection, roots, stable file snapshots, class API and dataset storage.
`use_cases/verify.py` orchestrates report-only checking or explicit cleanup;
`use_cases/dataset_bundle.py` prepares a new review directory, then separately
revalidates and publishes stable checked bytes. CLI owns decisions and exit codes;
public APIs never prompt and return structured missing decisions.

The prepared snapshot binds all four source CSVs, three payload hashes, options,
class decisions, roots and parent; preparation.sha256 binds the exact preparation.json
bytes against accidental record edits. Upload repeats media/data/root/class/parent
checks, refuses drift and publishes exactly dataset.csv, dataset.yaml and tasks.yaml.
Source copies, reports and images remain local. A newer exact finalized parent
requires preparation again. CSV-only legacy parents without metadata block.
Fetch no longer receives a publisher effect, reads ClearML mappings or initializes
ClearML; its export, partition, CVAT and S3 effects retain their established owners.
Executable layer, adapter-independence and effect checks apply to the new modules.

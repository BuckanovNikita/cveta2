# Python API

`import cveta2` exposes prompt-free functions that mirror the data commands of the CLI,
the lower-level `CvatClient`, the record and result types they return, and the
exception hierarchy. The functions run the same pipelines as the CLI and write the same
files. Connection settings come from `cveta2.Connection` or from configuration (see
[connection and configuration](connection-and-configuration.md)). The interactive
commands `setup`, `setup-cache` and `doctor` have no API counterpart.

## Package surface

`cveta2.__all__` is the supported surface. Names resolve lazily on first attribute
access, so `import cveta2` and the inner packages load no CVAT, S3, ClearML or
prompt SDK. `cveta2.__version__` holds the package version.

| Group | Names |
| -- | -- |
| CVAT workflow functions | `fetch`, `fetch_task`, `upload`, `whats_new`, `s3_sync`, `get_labels`, `update_labels`, `ignore`, `task_mark_deleted`, `task_drop_label`, `task_delete`, `task_set_status` |
| Local functions | `merge`, `convert_to_yolo`, `convert_from_yolo`, `convert_to_coco`, `partition_annotations_df` |
| Verification and standalone bundles | `verify`, `verify_dataframe`, `schema_for`, `prepare_dataset`, `upload_dataset`, `ValidationOptions`, `ValidationResult`, `Issue`, `Profile`, `PrepareOptions`, `PreparedDataset`, `MissingDecisions`, `Publication`, `DatasetInputError`, `DatasetWarning` |
| Managed datasets | `list_datasets`, `show_dataset`, `dataset_versions`, `fetch_dataset`, `prepare_managed_dataset`, `compare_datasets`, `report_dataset_errors`, `publish_dataset` |
| Connection and client | `Connection`, `CvatClient`, `CvatConfig`, `FetchContext`, `CvatApiPort` |
| Results and records | `PartitionResult`, `UploadResult`, `WhatsNewResult`, `AnnotationRecord`, `BBoxAnnotation`, `ImageWithoutAnnotations`, `DeletedImage`, `TaskAnnotations`, `ProjectAnnotations`, `TaskInfo`, `ProjectInfo`, `LabelInfo`, `LabelAttributeInfo`, `IgnoredTask` |
| Constants and literal types | `CSV_COLUMNS`, `JOB_STAGES`, `JOB_STATES`, `JobStage`, `JobState`, `Split` |
| Exceptions | `Cveta2Error`, `CvatApiError`, `MissingHostError`, `MissingCredentialsError`, `ProjectNotFoundError`, `TaskNotFoundError`, `InteractiveModeRequiredError`, `LabelsMismatchError` |

## Workflow functions

Every CVAT function takes a project spec (`int` ID, name, `"ORG/NAME"` or `"/NAME"`;
see [connection and configuration](connection-and-configuration.md)) and a keyword-only
`connection: Connection | None = None`. Task specs are `int` IDs or names.

| Function | Signature (keyword-only after `*`) | Returns | Behavior |
| -- | -- | -- | -- |
| `fetch` | `(project, output_dir, *, completed_only=False, skip_validation=False, raw=False, images_dir=None, download_images=True, cache="use", save_tasks=False, connection=None)` | `PartitionResult` | [fetch and partition](fetch-and-partition.md) |
| `fetch_task` | `(tasks, output_dir, *, project=None, completed_only=False, images_dir=None, download_images=True, cache="use", save_tasks=False, connection=None)` | `pandas.DataFrame` with `CSV_COLUMNS` | [fetch and partition](fetch-and-partition.md) |
| `whats_new` | `(project, dataset, *, connection=None)` | `WhatsNewResult` | [fetch and partition](fetch-and-partition.md) |
| `s3_sync` | `(project, target_dir, *, root=None, connection=None)` | `DownloadStats` | [images](images.md) |
| `upload` | `(dataset, project, name, *, labels=None, include_unannotated=False, exclude_in_progress=None, image_dirs=None, complete=False, mark_all_deleted=False, resume=False, connection=None)` | `UploadResult` | [upload and project management](upload-and-project-management.md) |
| `get_labels` | `(project, *, connection=None)` | `list[LabelInfo]` | [upload and project management](upload-and-project-management.md) |
| `update_labels` | `(project, *, add=None, rename=None, delete=None, recolor=None, connection=None)` | `None` | [upload and project management](upload-and-project-management.md) |
| `ignore` | `(project, *, add=None, remove=None, description="", silent=False, connection=None)` | `list[IgnoredTask]` | [upload and project management](upload-and-project-management.md) |
| `task_mark_deleted` | `(project, task, *, frames=None, images=None, connection=None)` | `int` | [upload and project management](upload-and-project-management.md) |
| `task_drop_label` | `(project, task, label, *, connection=None)` | `int` | [upload and project management](upload-and-project-management.md) |
| `task_delete` | `(project, task, *, connection=None)` | `None` | [upload and project management](upload-and-project-management.md) |
| `task_set_status` | `(project, task, *, stage=None, state=None, connection=None)` | `int` | [upload and project management](upload-and-project-management.md) |
| `merge` | `(old, new, output, *, deleted=None, in_progress=None, by_task=False)` | `pandas.DataFrame` | [conversion and merge](conversion-and-merge.md) |
| `convert_to_yolo` | `(dataset, output_dir, *, image_dirs=None, link_mode="auto")` | `Path` | [conversion and merge](conversion-and-merge.md) |
| `convert_from_yolo` | `(input_dir, output_csv, *, names_file=None, read_all_sizes=False, image_dirs=None)` | `Path` | [conversion and merge](conversion-and-merge.md) |
| `convert_to_coco` | `(dataset, output_dir, *, image_dirs=None, link_mode="auto")` | `Path` | [conversion and merge](conversion-and-merge.md) |
| `partition_annotations_df` | `(df, deleted_images)` | `PartitionResult` | [fetch and partition](fetch-and-partition.md) |
| `verify` | `(path, *, profile="cveta2", options=None, output_dir=None, clean=False)` | `ValidationResult` | [verification and bundles](verification-and-bundles.md) |
| `verify_dataframe` | `(frame, *, profile="cveta2", options=None)` | `ValidationResult` | [verification and bundles](verification-and-bundles.md) |
| `schema_for` | `(profile)` | pandera `DataFrameSchema` | [verification and bundles](verification-and-bundles.md) |
| `prepare_dataset` | `(source, *, output_dir, options)` | `PreparedDataset` | [verification and bundles](verification-and-bundles.md) |
| `upload_dataset` | `(prepared_dir)` | `Publication` | [clearml publication](clearml-publication.md) |
| `list_datasets`, `show_dataset`, `dataset_versions`, `fetch_dataset`, `prepare_managed_dataset`, `compare_datasets`, `report_dataset_errors`, `publish_dataset` | Each takes keyword-only `config_path: Path \| None = None` and `project_config: Path \| None = None` | see the managed file | [managed datasets](managed-datasets.md) |

- `cache` is `"use"`, `"refresh"` or `"off"` (`cveta2.api.CacheMode`); any other value
  raises `Cveta2Error`. Only `fetch` takes `skip_validation`.
- `task_set_status` takes CVAT values: `stage` from `JOB_STAGES`
  (`annotation`, `validation`, `acceptance`) and `state` from `JOB_STATES`
  (`new`, `in progress`, `completed`, `rejected`, with a space). Neither given raises
  `Cveta2Error`; an unknown value raises
  `Недопустимый stage '<value>'; допустимые: …` or `Недопустимый state '<value>'; допустимые: …`.
- `task_mark_deleted` without `frames` and `images` raises
  `Укажите хотя бы один frame или image.`
- The managed functions select the shared file only from `project_config`,
  `CVETA2_PROJECT_CONFIG` or the saved personal reference, never prompt, and report a
  needed migration as `MigrationRequired`.

## Connection

`Connection` is a frozen dataclass; all fields default to `None`.

| Field | Meaning |
| -- | -- |
| `host`, `username`, `password`, `organization` | Explicit values; they win over environment, personal file and preset |
| `config_path` | Personal file to load instead of `CVETA2_CONFIG` / the default; also the file named in credential errors |
| `client` | A ready `CvatClient` to reuse |

- Each call without `client` opens its own session and closes it before returning,
  also on error. It installs the request timeout, retry budget and worker counts from
  the selected configuration for the calling context.
- An injected `client` must already be entered (`with CvatClient(cfg) as client:`) or
  constructed with `api=`; otherwise the call raises
  `Переданный client не готов к работе: войдите в его контекст (with CvatClient(cfg) as client: ...) или создайте его с фейковым api=.`
  The function never enters or closes it.
- `None` and `""` fields fall through to lower sources, except
  `organization=""`, which selects the personal workspace.
- With a shared file selected (through `CVETA2_PROJECT_CONFIG` or the saved
  reference; `Connection` has no shared-file field), a `host`, `organization` or
  injected client that differs from the shared identity raises `Cveta2Error`.
- A resolved host that is empty raises `MissingHostError`
  (`Хост CVAT не настроен. Передайте host= или задайте CVAT_HOST (либо cvat.host в конфигурации).`);
  with the bundled preset the host resolves to at least `http://localhost:8080`, so an
  unconfigured host reaches that default rather than this error. Missing credentials
  raise `MissingCredentialsError` when the session opens.

## Prompt-free guarantee

API functions and `CvatClient` never prompt, never read standard input and never call
`sys.exit`; missing input raises an exception instead. Interactive prompts, project and
task pickers and confirmations exist only in the CLI. Missing standalone-preparation
decisions come back as `MissingDecisions.decisions` (see
[verification and bundles](verification-and-bundles.md)).

## CvatClient

`CvatClient(cfg: CvatConfig | None = None, client_factory=None, *, api: CvatApiPort | None = None)`
gives direct access to CVAT. Without `cfg` it loads `CvatConfig.load()` (preset, then
personal file, then environment, with shared identity). `api=` injects a port
implementation instead of a real session.

- Remote methods require the context manager. Outside it they raise `RuntimeError`
  `<method>() requires a context manager. Use: with CvatClient(cfg) as client: ...`.
  Entering checks credentials and raises `MissingCredentialsError` when they are
  missing; leaving closes the SDK session.
- A directly constructed client runs fetch with one CVAT worker and the default retry
  budget; the request timeout from `cfg` applies when the session opens.
- `organization` is the current session organization (`None` = personal workspace);
  `default_organization` is the configured one; `set_organization(org)` switches the
  session and forgets memoized cloud storage. `host` and `is_ready` are properties.

| Method | Returns |
| -- | -- |
| `list_organizations()` | `list[OrganizationInfo]` (`slug`, `name`) |
| `list_projects()` | `list[ProjectInfo]` of the session organization |
| `get_project(project_id)` | `ProjectInfo` |
| `resolve_project_id(spec, *, cached=None)` | `int`; a decimal spec is returned as is |
| `find_project_by_name(name, *, cached=None)` | `ProjectInfo` with CVAT's spelling; ambiguity raises `Cveta2Error`, no match `ProjectNotFoundError` |
| `list_project_tasks(project_id)`, `get_task(task_id)`, `get_task_size(task_id)` | `list[TaskInfo]`, `TaskInfo`, `int` |
| `list_new_completed_tasks(project_id, cutoff, known_task_ids)` | `list[TaskInfo]` |
| `get_project_labels(project_id)`, `count_label_usage(project_id)`, `label_usage(project_id)` | `list[LabelInfo]`, `dict[int, int]`, `LabelUsage` (`counts`, `skipped_task_ids`, `complete`) |
| `detect_project_cloud_storage(project_id)` | `CloudStorageInfo \| None`, memoized per project for the client's lifetime |
| `prepare_fetch(project_id, *, completed_only=False, ignore_task_ids=None, silent_task_ids=None, task_selector=None, project_name="")` | `FetchContext` |
| `CvatClient.fetch_one_task(api, task, ctx)` (static) | `TaskAnnotations \| None` (`None` for a skipped task) |
| `CvatClient.resolve_task_selectors(tasks, selectors)` (static) | `list[TaskInfo]` |
| `download_images(annotations, target_dir, project_id=None, project_cloud_storage=None, ignored_prefix=None)`, `sync_project_images(project_id, target_dir, project_cloud_storage=None, ignored_prefix=None)` | `DownloadStats` (`downloaded`, `cached`, `failed`, `total`) |
| `create_upload_task(project_id, name, image_names, cloud_storage_id, segment_size=100, image_quality=100, *, on_created=None)` | task ID |
| `upload_task_annotations(task_id, annotations_df, *, session=None)`, `create_task_issues(task_id, annotations_df, *, session=None, skip_existing=False)` | count written |
| `mark_frames_deleted(task_id, image_names, *, session=None)`, `mark_frames_deleted_by_ids(task_id, frame_ids)` | count of newly deleted frames |
| `update_project_labels(project_id, *, add=None, rename=None, delete=None, recolor=None)` | `None` |
| `count_task_shapes(task_id)`, `count_task_label_shapes(task_id, label)`, `drop_label_annotations(task_id, label)` | `int` |
| `delete_task(task_id)`, `set_task_jobs_status(task_id, *, stage=None, state=None)`, `complete_task(task_id)` | `None`, jobs updated, jobs updated |
| `open_task_session(task_id)` | `TaskWriteSession` for consecutive writes to one task |

The behavior of these operations belongs to the feature files linked from the
workflow-function table.

## Results and records

| Type | Fields |
| -- | -- |
| `PartitionResult` (dataclass) | `dataset`, `obsolete`, `in_progress` (`pandas.DataFrame`), `deleted_images`, `pending_deletions`, `reopened_deletions` (`list[DeletedImage]`) |
| `UploadResult` | `task_id`, `task_name`, `url`, `images`, `deleted`, `annotations`, `issues` |
| `WhatsNewResult` | `tasks: list[TaskInfo]`, `cutoff: int` |
| `TaskAnnotations` | `task_id`, `task_name`, `annotations`, `deleted_images`, `issues_complete`; `TaskAnnotations.merge(list)` returns `ProjectAnnotations` |
| `ProjectAnnotations` | `annotations: list[AnnotationRecord]`, `deleted_images: list[DeletedImage]` |
| `AnnotationRecord` | `BBoxAnnotation \| ImageWithoutAnnotations`, discriminated by `instance_shape` |
| `TaskInfo` | `id`, `name`, `status`, `subset`, `updated_date`, `project_id` |
| `ProjectInfo` | `id`, `name` |
| `LabelInfo` | `id`, `name`, `color`, `attributes`, `type`, `svg`, `sublabels`, `project_id`, `task_id`, `parent_id`, `has_parent` |
| `LabelAttributeInfo` | `id`, `name`, `mutable`, `input_type`, `default_value`, `values` |
| `IgnoredTask` | `id`, `name`, `description`, `silent` |
| `CvatConfig` | `host`, `organization`, `username`, `password`, `request_timeout` |
| `FetchContext` (dataclass) | `tasks`, `label_names`, `attr_names`, `host`, `project_name`, `raise_on_failure`, `all_task_ids` |

Record fields and the CSV columns (`CSV_COLUMNS`) are described in
[fetch and partition](fetch-and-partition.md); verification, bundle and managed result
types in their own files. `Connection`, `UploadResult` and `WhatsNewResult` pickle under
the module path `cveta2.interfaces.api`, and pickles written under that path load.

## Exceptions and the error boundary

Every expected cveta2 failure derives from `Cveta2Error`.

| Exception | Raised when |
| -- | -- |
| `CvatApiError(message, status_code=0, retry_after=None, *, diagnostics=None)` | A CVAT request failed; `status_code` 0 when unknown, `retry_after` the parsed `Retry-After` seconds |
| `MissingHostError`, `MissingCredentialsError` | No host, or no username and password, after resolution |
| `ProjectNotFoundError`, `TaskNotFoundError` | A named project or task does not exist |
| `InteractiveModeRequiredError` | A CLI prompt was needed in non-interactive mode or without standard input |
| `LabelsMismatchError` | Upload labels are missing from the project; `unknown_labels`, `available_labels` |
| `MissingDecisions`, `DatasetInputError` | See [verification and bundles](verification-and-bundles.md) |
| `ManagedError`, `MigrationRequired` (`cveta2.domain.managed.models`) | Shared configuration, migration and managed-dataset failures |

`cveta2.exceptions` also exports `CvatRequestDiagnostics` and `ClearmlPublishError`.

`CvatRequestDiagnostics` is a frozen dataclass carried by `CvatApiError.diagnostics`
(`None` for errors without HTTP context):

| Field | Type |
| -- | -- |
| `operation` | `str`; the cveta2 operation name, `cvat_request` when unknown |
| `method` | `str` |
| `endpoint` | `str`; sanitized URL |
| `resource_ids` | `tuple[tuple[str, int], ...]` |
| `timestamp_utc` | timezone-aware UTC `datetime` |
| `status_code` | `int`, 0 when unknown |
| `request_ids` | `tuple[tuple[str, str], ...]` |
| `response_summary` | `str`, bounded and sanitized |

It holds no SDK objects. Sanitizing rules are in
[connection and configuration](connection-and-configuration.md).

Boundary rules:

- The original cause stays on `__cause__` (SDK exception, parser error, OS error).
- S3 failures in image download, sync and upload reach API callers as the original
  botocore/boto3 exception (`ClientError`, `NoCredentialsError`, `ProfileNotFound`,
  `EndpointConnectionError` and the like), with a note in `__notes__` reading
  `S3: <operation> s3://<bucket>/<prefix>`. The CLI translation and the per-object
  failures that are counted instead are in [images](images.md).
- Invalid configuration values (a negative `request_timeout`, an out-of-range
  `network` value) raise pydantic `ValidationError` in the API; the CLI prints
  `Некорректная конфигурация: <field>: <message>. Проверьте YAML и переменные окружения.`
- The CLI prints any `Cveta2Error` message and exits with code 1 without a traceback;
  commands with their own exit codes are described in their feature files. Other
  exceptions are unexpected defects and keep their traceback.

## Compatibility facades

These top-level modules re-export canonical implementations under stable import paths;
each exported object is the same object as its canonical one.

| Module | Exports |
| -- | -- |
| `cveta2.api` | The workflow, verification and managed functions and types, plus `CacheMode` |
| `cveta2.client` | `CvatClient`, `FetchContext`, `TaskWriteSession` |
| `cveta2.config` | `CvatConfig`, section models (`CacheConfig`, `ImageCacheConfig`, `IgnoreConfig`, `NetworkConfig`, `SyncRootsConfig`, `UploadConfig`, `SectionConfig`), `CacheProjectSettings`, `IgnoredTask`, `CONFIG_DIR`, `CONFIG_PATH` and the path, cache and mode helpers |
| `cveta2.exceptions` | `Cveta2Error`, `CvatApiError`, `MissingHostError`, `MissingCredentialsError`, `ProjectNotFoundError`, `TaskNotFoundError`, `InteractiveModeRequiredError`, `LabelsMismatchError`, `CvatRequestDiagnostics`, `ClearmlPublishError` |
| `cveta2.models` | Records, `CSV_COLUMNS`, `JOB_STAGES`, `JOB_STATES`, `COMPLETED_JOB_STAGE`, `COMPLETED_JOB_STATE`, `OrganizationInfo` |
| `cveta2.dataset_partition` | `PartitionResult`, `partition_annotations_df`, `completed_task_ids` |
| `cveta2.projects_cache` | Projects-cache readers and writers, `PERSONAL_WORKSPACE_SLUG`, `PERSONAL_WORKSPACE_TITLE` |
| `cveta2.image_downloader`, `cveta2.image_uploader` | Image transfer classes and `CloudStorageInfo`, `DownloadStats`, `UploadStats` |
| `cveta2.s3_types`, `cveta2.s3_utils` | S3 client types and helpers |
| `cveta2.task_cache` | Annotation-cache classes, `CACHE_SCHEMA_VERSION`, `invalidate_local_entry` |
| `cveta2.upload_manifest` | Upload manifest model and helpers |
| `cveta2.fs_utils` | Shared-permission file helpers |
| `cveta2.cli` | `main`, `CliApp`, `CommandSpec`; the `cveta2` console script runs `cveta2.cli:main`, and `python -m cveta2` runs the same CLI |

The CVAT workflow functions and `merge` report `cveta2.interfaces.api` as their
`__module__`.

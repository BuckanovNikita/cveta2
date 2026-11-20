# cveta2 reference

Agent rules and check commands are in [AGENTS.md](AGENTS.md); usage in [README.md](README.md).

## Architecture and data flow

- Fetch: interfaces → `composition/workflows.py` → `application/use_cases/fetch.py:fetch_project()` → `ApplicationClient.fetch_one_task()` per task (concurrent, merged positionally) → `adapters/cvat/sdk_adapter.py`; result `ProjectAnnotations(annotations, deleted_images)` is partitioned into four CSVs. `output/.tasks/task_<id>.csv` only with `save_tasks=True`; a debug artifact, never a resume point.
- Upload: `interfaces/commands/upload.py` → `composition/workflows.py` → `application/use_cases/upload/orchestration.py:upload_dataset()`. Stage order (keep it): name/box validation and fingerprint, lock held for the run, input/manifest/resume checks before the first S3 write, manifest saved before create, task ID saved before data attach, pending mark before any shape write, counts saved before manifest deletion. Nothing is retried from an unknown create outcome.
- CVAT transport (`adapters/cvat/transport.py`): context-local timeouts and read / non-idempotent-write / idempotent-write policies. Non-GET/HEAD/OPTIONS copies of the SDK retry policy disable read, status and Retry-After retries (connect retries kept). Final 502/503/504 reach the per-task 5xx skip policy (`application/client/shared.py`); a required-read 429 aborts. Log lines "попытка cveta2 N/M" count only the outer layer.
- Project resolution (`application/use_cases/resolve.py`): id, name, `ORG/NAME`, `/NAME` (personal space); org prefix calls `set_organization()`; names case-insensitive, CVAT spelling returned; an ambiguous name is rejected listing IDs. A numeric spec is named from the projects cache or one `get_project`, never by listing the organization. Projects cache: `organizations: [{slug, name, projects}]`, empty slug = personal.
- Config (`adapters/config/project.py`): shared policy and personal storage are separate files; activation is shared-first and recoverable through a migration journal (paths and hashes only), not atomic. `setup` owns preview and approval; loading never prompts.
- `ConcurrentRunner`: ordered outcomes, caught per-item failures stay outcomes, an uncaught failure cancels queued work and joins active work.
- Managed datasets: `composition/managed.py` injects every effect as a typed port; `domain/managed/models.py` `source_fingerprint` (snapshot `definition_hash`, drives "fetch again") and `definition_fingerprint` (preparation record and published `dataset.yaml`) are the only implementations of those hashes. `domain/managed/policies.py` receives image hashes and never reads files.

## Domain terms

- Partition outputs: dataset (latest completed task per live image), obsolete (older completed rows and deleted images' rows), in_progress (unfinished tasks plus `instance_shape="deleted"` pending and reopened deletions), deleted (images deleted by the latest completed task).
- Pending deletion: deletion inside an unfinished task; image stays in dataset. Reopened deletion: image deleted by a completed task and held by a newer unfinished task; leaves deleted and dataset, last completed rows go to in_progress.
- Standalone preparation: four full-fetch CSVs with externally assigned splits. Managed preparation: named shared dataset definition with captured sources, optional transformation and persistent splits. Source evidence: captured annotations before transformation. Prepared bundle: local publication input for review (ready ≠ reviewed/published). Parent dataset: exact finalized nonarchived version a publication continues.
- Class identity: API field `number` = `ClassInfo.prod_id`; `ClassInfo{prod_id, empty=false, alt_names}`.

## Decisions

- Product contracts (Linear, authoritative since 2026-11-17, SIP-66): [index](https://linear.app/sip-ds-team/document/cveta2-product-contract-index-0f712c7810f8); [CLI](https://linear.app/sip-ds-team/document/contract-docsclimd-ccd8081c0258), [configuration](https://linear.app/sip-ds-team/document/contract-docsconfigurationmd-67789ec2f0b6), [dataset contract](https://linear.app/sip-ds-team/document/contract-docsdataset-contractmd-ffd41fecfde2), [Python API](https://linear.app/sip-ds-team/document/contract-docspython-apimd-a72b44e6c704), [images and cache](https://linear.app/sip-ds-team/document/contract-docsimages-and-cachemd-533d3ab25cef), [baseline](https://linear.app/sip-ds-team/document/contract-specsbaselinemd-2331f5c7c87b), [glossary](https://linear.app/sip-ds-team/document/contract-glossarymd-a4613e4e8529).
- SIP-82: annotation-cache freshness is per job (id/type/range/stage/state/`updated_date`); a state-only change must be seen by the next fetch.
- Task verification: Task owns sequential commands, testmon owns test selection; no freshness cache, success receipts, shared result cache or verification CI. `test` excludes `tests/integration` by directory because a marker expression forces `--testmon-noselect`. Git hooks were removed (SIP-159); checks run directly.
- Release: merge-triggered GitHub Actions semantic-release (SIP-143); version lives only in `cveta2/__init__.py` (SIP-149).

## CLI

`cveta2 --help` lists the commands; `cveta2 <command> --help` lists every flag.
- `setup --migrate-config` previews the split, needs confirmation, writes a protected backup; cancel changes nothing; a rerun finishes an interrupted confirmed activation. `setup-cache [--reset|--list]` saves `cache.images_root`, `cache.tasks_root`, optional per-project `ignored_prefix`, `task_cache_s3`.
- `doctor`: exit 0 when CVAT host and credential checks pass, else 1; AWS/path/permission warnings advisory. `doctor --cache` adds group rwx/rw on paths the user owns; never changes group or setgid.
- `fetch --skip-validation`: when a task's nonempty job list is only annotation/completed and acceptance/completed, promote the former to acceptance/completed after mandatory cache invalidation; any failure aborts before annotation reads; not rolled back; fetch only.
- `fetch-task -p P -t ID|NAME...` writes unpartitioned dataset.csv and deleted.csv; bare `-t` opens a picker; without `-p` the project comes from the first numeric task ID.
- Shapes: rectangles export; a polygon becomes its tight axis-aligned box (rotation 0, no rounding, warning); polygons with <3 points, odd counts, NaN/inf or zero size skip; tracks and other shapes skip with a warning.
- `whats-new -d dataset.csv` reads sibling obsolete/deleted and completed in_progress rows; needs `job_stage`/`job_state` columns; cutoff = max completed task_id (informational).
- `s3-sync [--root s3://b/p -p P]` downloads only missing files, never writes S3; `sync_root` applies to s3-sync and fetch downloads, never upload. S3 failures exit nonzero with "Ошибка S3 (<операция> s3://...)"; dataset s3-csv sources exit 2.
- `upload`: frames follow CSV order; images found recursively by basename (lexicographically last wins); new S3 images under `YYYY-MM/`; missing images or failed S3 upload abort before task creation. Label selection is per frame. Issues only from rows with `issue_state="new"`, nonempty `issue_text` and a full bbox. `image_name` must be a safe relative path. `--labels all` includes unannotated frames unless a label named `all` exists.
- `merge`: new wins by default; `--by-task` picks higher task_id (ties to new); an empty winning split inherits the old one.
- `convert --to-yolo` needs split train/val/test on every row, clips boxes, drops zero-size after rounding to 6 decimals, removes stale files, aborts on symlinked outputs. `--from-yolo`: dataset mode with dataset.yaml, else predictions mode with `--names-file` and optional confidence; malformed lines skipped with file:line. `--to-coco`: train/valid/test with `_annotations.coco.json`, category IDs from 1, `[x,y,w,h]` unclipped; re-export replaces only files its metadata owns.
- `labels -p P [--list]`: add, rename (by ID, keeps annotations), recolor `#rrggbb`, delete (irreversible; typed confirmation when usage is nonzero or unknown).
- `ignore` entries are stored in shared `projects.<key>.ignore`.
- Every `task` subcommand invalidates local and S3 cache. API `task_set_status` takes CVAT `'in progress'` (with a space).
- Non-interactive (`CVETA2_NO_INTERACTIVE=true`): setup unavailable; setup-cache `--list` only; fetch needs `-p`; upload needs `-p --name --labels`; labels `--list` only; ignore needs an action; `task drop-label|delete` need `--yes`. fetch overwrites output dirs; verify and prepare refuse existing ones.

## Configuration

- Personal YAML (`schema_version: 1`; `--config` > `CVETA2_CONFIG` > `~/.config/cveta2/config.yaml`): `project_config`, `cvat{username,password,request_timeout}`, `image_cache{project:path}`, `cache{images_root,tasks_root}`, `network{s3_workers:16,cvat_workers:4,retry_attempts:5,retry_max_wait:30.0}`, `upload{images_per_job:100,image_quality:100}`. Defaults: model fields in `cveta2/adapters/config/settings.py`, plus `cveta2/presets/default.yaml` (host, upload).
- Shared YAML (`schema_version: 1`; `--project-config`/API arg > `CVETA2_PROJECT_CONFIG` > personal `project_config`; saved relative refs resolve from the personal file's dir): `cvat{host,organization}`, `projects.<key>{id,name,sync_root,ignored_prefix,task_cache_s3,ignore}`, `datasets.<name>{sources[{name,type:cvat|s3-csv,project|uri}],clearml{project,dataset},api_url,s3_roots,empty_classes,splits{train,val,test,seed},overlaps}`. No secrets or local paths. Writes take a nonblocking lock on sibling `.<filename>.lock` (never delete it), write only changed projects, fail on concurrent same-field edits.
- Env: `CVETA2_CONFIG`, `CVETA2_PROJECT_CONFIG`, `CVAT_USERNAME`, `CVAT_PASSWORD`, `CVAT_HOST`, `CVAT_ORGANIZATION` (conflict with shared identity rejected), `CVETA2_DATA_TIMEOUT`, `CVETA2_S3_WORKERS`, `CVETA2_CVAT_WORKERS`, `CVETA2_RETRY_ATTEMPTS`, `CVETA2_NO_INTERACTIVE`, `CVETA2_DISABLE_CACHE`, `CVETA2_RAISE_ON_FAILURE`. Env overrides personal credentials and network values; server/organization values conflicting with the shared file are rejected; project rules never come from the personal file.
- Retries: reads on 429/500/502/503/504 and network faults; idempotent job-state and deleted-frame writes on 429/500/502/503/504; non-idempotent writes on 429 only. During fetch a 5xx on one task skips it and logs a `cveta2 ignore --project ... --add ID` hint (`CVETA2_RAISE_ON_FAILURE=true` fails instead); exhausted 429 aborts (lower `network.cvat_workers`). S3 retries SlowDown, RequestTimeout, RequestTimeTooSkewed, InternalError, 503; never 403/404.
- API and `CvatClient` never prompt: `MissingHostError`, `MissingCredentialsError`. `CvatApiError(message, status_code=0, retry_after=None, *, diagnostics=None)`; `CvatRequestDiagnostics` holds operation, method, endpoint, resource_ids, timestamp_utc, status_code, request_ids (`X-Request-Id`), response_summary; no cookies, credentials or raw HTML.
- ClearML extra: `uv add "cveta2[clearml] @ git+ssh://git@<host>/<org>/cveta2@vX.Y.Z"`; ClearML and S3 credentials come from standard SDK configuration.

## Dataset contract

- `CSV_COLUMNS` (30, ordered): image_name, image_width, image_height, instance_shape (box|none|deleted), instance_label, bbox_x_tl, bbox_y_tl, bbox_x_br, bbox_y_br, task_id, task_name, job_stage, job_state, task_completed, task_updated_date, created_by_username, frame_id, split, subset, occluded, z_order, rotation, source, annotation_id, confidence, issue_text, issue_state, s3_image_path, image_path, attributes (JSON). Fetch never sets `split`.
- One row per box. `image_name` is the basename; nested frames keep the full key in internal `frame_path` (not in CSV); S3 keys and local cache keep subdirectories (`ignored_prefix` strips a top prefix). Traversal and outside-root names are rejected.
- Issues repeat on every row of a frame; comments join with `; `, issues with ` | `; exported states open/resolved; `new` is reserved for upload.
- Partition (`domain/partition.py`, specified by `tests/test_partition.py::test_partition_matches_specification`): the latest completed task by `task_id` decides each image; completion needs every job at acceptance/completed.

## Images and cache

- Downloads use the project's `source_storage`. Up to 2000 uncached images (`_DIRECT_KEY_PROBE_LIMIT`, `adapters/s3/download.py`) GET canonical keys directly, falling back to prefix/basename lookup only for missing keys; larger batches list first. Cache dirs get 0775/0664. Default path `<cache.images_root>/<encoded project name>`. S3 credentials only from the boto3 chain.
- Annotation cache (`CACHE_SCHEMA_VERSION = 6`, `domain/cache.py`): per job, only acceptance/completed jobs with a modification date, plus `meta.json` (frames, issues); one `task.json` for GT, consensus or overlapping-range tasks. Local `~/.cache/cveta2/task_annotations/project_<id>/task_<id>/` (honors `XDG_CACHE_HOME`, `cache.tasks_root`); S3 `<project prefix>/.cveta2_cache/task_annotations/task_<id>/` (with `task_cache_s3`: `<prefix>/task_annotations/`). Schema ≤5 entries are deleted. A fully cached task costs one request. upload and `task *` clear both. `--no-cache`, `--force`, `CVETA2_DISABLE_CACHE=true` override.
- Upload resume state (`MANIFEST_SCHEMA_VERSION = 3`, `domain/upload.py`): `~/.cache/cveta2/uploads/<host-hash>/project_<id>/<fingerprint>.json` with an exclusive `flock` on `<fingerprint>.lock` (`UploadInProgressError`). It binds host and full intent; older manifests cannot resume. Resume verifies server, project and actual task content (shapes append); issues match by (frame, first message, bbox). A CVAT 4xx other than 408/429 means not created. An interrupted write that left the task empty waits 30 s, rereads, then sends.

## Python API

- Functions: `fetch` (→ `PartitionResult`: dataset, obsolete, in_progress, deleted_images, pending_deletions, reopened_deletions; `cache='use'|'refresh'|'off'`; `skip_validation=False`), `fetch_task`, `upload` (→ `UploadResult`: task_id, task_name, url, images, deleted, annotations, issues), `convert_to_yolo`, `convert_from_yolo`, `convert_to_coco`, `merge`, `whats_new` (.tasks, .cutoff), `s3_sync`, `get_labels`, `update_labels`, `ignore`, `task_mark_deleted`, `task_drop_label`, `task_set_status`, `task_delete`.
- `connection=cveta2.Connection(host, username, password, organization, config_path, client=)`; `client=` reuses an open `CvatClient`. `CvatClient(cfg=None, client_factory=None, *, api=None)` needs `with`; it exposes `prepare_fetch`, `fetch_one_task`, `download_images` (project_id required), `sync_project_images`, `update_project_labels`.
- Verification: `verify(path, *, profile='cveta2', options=None, output_dir=None, clean=False)`, `verify_dataframe`, `schema_for`, `ValidationOptions(iou_threshold=0.99, check_images=False, image_root=None, base_dir=None, emit_warnings=True)`, `prepare_dataset(source, *, output_dir, options)` raising `MissingDecisions(.decisions)`, `upload_dataset` → `Publication(dataset_id, version)`.
- Managed: `list_datasets`, `show_dataset`, `dataset_versions`, `fetch_dataset(refresh=)`, `prepare_managed_dataset`, `compare_datasets`, `report_dataset_errors`, `publish_dataset`; each takes `config_path` and `project_config`.
- S3 errors surface as original botocore exceptions with `__notes__`; managed s3-csv sources raise `ManagedError`.

## Verification, preparation and publication

- `verify CSV --output-dir NEW` (`--iou-threshold` defaults to 0.99) writes report.json, broken.csv (+ clean.csv); never overwrites input. Exit 0 pass, 1 findings or cancel, 2 input/config/operational error.
- `verify DIR --bundle` needs dataset/obsolete/in_progress/deleted CSVs, `--project` (exact ClearML project), `--dataset-name`, `--api-url`, `--local-root`/`--s3-root`/`--empty-class` (repeatable), `--accept-default-classes`, `--accept-class-changes`, `--non-interactive`, `--clean`. Splits preassigned; train and val nonempty with ≥1 train box; images ≥10 px per side; box sides and area >2.
- Prepared dir: `sources/{4 csv}`, report.json, broken-images.csv, dataset.csv, dataset.yaml (api_url, classes, images.local_root/s3_root), tasks.yaml (sorted included/obsolete task IDs; managed adds source evidence), preparation.json (format_version 1 standalone, 2 managed), preparation.sha256 written last (accident check, not a signature).
- `upload-dataset PREPARED` rechecks hashes, media, roots, classes and latest parent, then publishes exactly dataset.csv, dataset.yaml, tasks.yaml. Exit 0 finalized, 1 cancel, 2 blocked/error. Parent = latest finalized nonarchived version with exact project/name; a CSV-only parent blocks (use a new name). First publish creates the project and a parentless version.

## Managed datasets

- `dataset` mapping parameters are not overridable by flags.
- `fetch [--refresh]`: per-source reuse; a new/renamed source or changed CVAT project ID refetches only that source; S3 CSV reread every time; full refetch on CVAT server/org or class registry change, or a parent published before 0.14.0. Snapshot format 1 has additive `registry` and per-source `labels`.
- `prepare NAME transformed.csv --source FETCHED --output-dir OUT [--clean]` (OUT outside source): stable splits, default 60/20/20 seed 42 (`splits` must sum to 1, train and val >0). A published lineage's split policy cannot change; use a new dataset name.
- After prepare, a change to splits, overlaps, empty_classes, s3_roots, api_url or clearml needs prepare again; a changed clearml parent or class registry needs a refetch. Source order, project name, sync_root, ignored_prefix, task_cache_s3 and ignore metadata change nothing.
- `report-errors` creates CVAT issues only for errors with provable project/task/frame; receipts in feedback.json (format_version 1) prevent duplicates; failed delivery blocks publish, which can resume it. `diff` takes local CSVs/dirs or ClearML version IDs; ready=false exits 1; config/source/publish errors exit 2.

## Live test infrastructure

- `python -m tests.integration.lifecycle check|up|env|stop [<ns>]`; full interface in its module docstring. `up` exits 0, 3 blocked, 1 error and records `tests/integration/.session` (namespace and four ports, no credentials). `stop` accepts only `cveta2-it-` names, treats an absent namespace as success and kills only matching port-forwards.
- Preflight order: kubectl present, `/readyz`, `auth can-i create/delete namespaces`, a Ready, uncordoned, untainted node with unrequested CPU/memory ≥ quota requests. A ready or seed timeout is blocked setup: the namespace is deleted even with keep. A first CVAT image pull can exceed the ready deadline: pull once or raise `CVETA2_SESSION_READY_TIMEOUT`.
- The namespace is labelled `app.kubernetes.io/part-of=cveta2-integration` plus a random token; an uncertain create is cleaned only when the token matches. The namespace name is the run tag, MinIO bucket and `"<ns> "` object prefix (CVAT project `<ns> coco8-dev`, cloud storage `<ns> minio`).
- CVAT set: server, `import` and `chunks` workers (tests read `quality="original"`), initializer Job, OPA, Redis, kvrocks, PostgreSQL 15; no frontend, analytics, Nuclio or other workers. ClearML set: API server, file server, MongoDB, Elasticsearch 7.17.28, Redis; every ES host needs `"scheme":"http"`; file server waits for the API server; tests use the `tests` key pair.
- Quota (`k8s/quota.yaml`): sizes are the project's choice; change them, never remove the quota.

## Release operations

- `.github/workflows/release.yml` and `[tool.semantic_release]` in `pyproject.toml` define the release. It commits `chore(release): <version>`, tags `v<version>`, pushes `main` then the tag. No build, GitHub Release or package. Dry run: `uvx --from python-semantic-release==10.7.0 semantic-release --noop version`.
- Inspect: `gh run list --workflow release.yml`, `gh run view <id> --log`, `git ls-remote origin refs/heads/main 'refs/tags/v*'`; record run URL, SHAs, version and tag on the Linear issue.
- Failure before any push: nothing published; next merge or a human `gh run rerun` releases; a configuration error repeats on every merge, fix it through a PR. Commit without tag: a human reruns with nothing merged in between (merging first tags a HEAD whose changelog misses the change). Existing tag: "No release will be made, <version> has already been released!" exits 0 green; if that tag is not on `main`, every run computing that version skips green until a human investigates and removes the tag. Branch protection without an Actions-token bypass blocks the push; never weaken human protections.

## History

The full pre-compression documents are in git at commit 332dfb0: `git show 332dfb0:<path>`. An unmerged docs rebuild is on branch `docs/feature-files` (SIP-151).

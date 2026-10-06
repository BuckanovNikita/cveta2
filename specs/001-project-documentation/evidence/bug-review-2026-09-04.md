# Bug review

Review date: 2026-09-04

Scope: static review of the Python package and its tests, split across parallel audits of core data processing, client/cache/storage code, and CLI/API/configuration code. The full unit suite passed (`1529 passed`). Findings below are ordered by severity; passing tests do not cover these boundary cases.

## Disposition

- BR-01, BR-04, and BR-06 through BR-11: implemented on 2026-09-04 with regression coverage.
- BR-02: tracks remain unsupported by design; ignoring them is now visible through task-specific warnings and documentation.
- BR-03 and BR-05: accepted input contract. Frame paths are relative and basenames are unique within a project; duplicate-basename selection is intentionally undefined. Do not reopen these as defects unless that contract changes.

## Summary

| ID | Severity | Area | Impact |
|---|---|---|---|
| BR-01 | High | Image download / S3 sync | A frame name or object key can write outside the selected cache directory. |
| BR-02 | High | Annotation extraction | CVAT rectangle tracks are silently discarded. |
| BR-03 | High | Frame identity | Different nested frames with the same basename are conflated. |
| BR-04 | High | Task cache | Completed tasks can return stale annotations and labels indefinitely. |
| BR-05 | Medium | S3 lookup | Basename fallback selects the oldest duplicate instead of the documented latest one. |
| BR-06 | Medium | YOLO import | `dataset.yaml`'s dataset root is ignored. |
| BR-07 | Medium | Custom configuration | Setup commands read/write the default projects cache despite `--config`. |
| BR-08 | Medium | Configuration errors | Malformed YAML escapes the CLI as a traceback. |
| BR-09 | Medium | Python API organization selection | An explicit personal-workspace selection cannot override a configured organization. |
| BR-10 | Low | Deleted-frame operation | Already-deleted frames are counted as newly changed and trigger a redundant PATCH. |
| BR-11 | Low | Upload command echo | A prompted resume prints a command that no longer resumes. |

## Findings

### BR-01 — Download paths are not confined to the target directory

**Severity: High (security and data integrity)**

`ImageDownloader._dest_path()` joins the target directory with `frame_ref` without rejecting absolute paths or `..` components (`cveta2/image_downloader.py:189`). The resulting path is used for existence checks and writes (`cveta2/image_downloader.py:219`, `cveta2/image_downloader.py:254`). `S3Syncer.sync()` performs the same unchecked join for names derived from object keys (`cveta2/image_downloader.py:399`).

With `pathlib`, an absolute right-hand operand replaces the left-hand target, while `..` is resolved by filesystem operations. A CVAT frame name such as `../../escape.jpg`, or a crafted S3 object key below the configured prefix, can therefore make the command write outside the requested image cache. An existing outside file can also be incorrectly counted as cached.

**Suggested regression test:** download an annotation whose `frame_path` is `../../escape.jpg`, and sync an object whose relative key contains `..`; assert both operations reject the name and nothing outside `target_dir` is read or written.

**Suggested fix:** accept only normalized relative POSIX paths, reject absolute paths and traversal components, then verify `destination.resolve()` remains under `target_dir.resolve()` before any existence check or write.

### BR-02 — Rectangle tracks are silently omitted

**Severity: High (silent annotation loss)**

`convert_annotations()` converts only `labeled_data.shapes` (`cveta2/_client/sdk_convert.py:101`). The internal `RawAnnotations` representation has no tracks collection, and downstream assembly consequently sees no annotation for frames represented solely by CVAT tracks. Rectangle tracks are valid CVAT annotations, so affected frames can be exported as unannotated even though boxes exist.

**Suggested regression test:** build a `LabeledData` response with `shapes=[]` and one rectangle track containing tracked shapes. Assert the corresponding box rows are emitted rather than `ImageWithoutAnnotations` rows.

**Suggested fix:** flatten supported rectangle-track shapes into the internal annotation representation with explicit frame/track semantics. If tracks are intentionally unsupported, fail or emit a prominent incomplete-result warning instead of silently dropping them.

### BR-03 — Nested frames with equal basenames are treated as one image

**Severity: High (silent omission and incorrect partitioning)**

The model preserves a nested source name in `frame_path` but reduces `image_name` to its basename (`cveta2/models.py:126`). `frame_path` is then omitted from CSV rows (`cveta2/models.py:212`). Partitioning and conflict resolution use only `image_name`, so `jan/x.jpg` and `feb/x.jpg` compete as if they were the same frame. The downloader independently keys its unique-image map by the same basename, with first occurrence winning (`cveta2/image_downloader.py:172`).

Consequences include one of the two files not being downloaded, annotations from one path becoming obsolete because of the other path's task ID, and deletion records affecting the wrong frame.

**Suggested regression test:** use two completed tasks containing `jan/x.jpg` and `feb/x.jpg`; assert two downloads and two independently retained dataset identities. Add a deletion case to ensure one path cannot delete the other.

**Suggested fix:** retain a stable full relative frame identity through CSV export and use it for download, partition, deletion, and conflict keys. If the public format must remain basename-only, reject basename collisions explicitly rather than silently merging them.

### BR-04 — Completed-task cache ignores content changes

**Severity: High (persistent stale results)**

The cache envelope stores `task_updated_date`, but validation checks only schema version and task ID (`cveta2/task_cache.py:252`, `cveta2/task_cache.py:353`). Any live task still reported as `completed` is eligible for the cached payload. That payload already contains resolved label names, so a label rename or annotation edit made in CVAT or another client can remain invisible to normal fetches indefinitely, including through the shared S3 cache.

The deliberate reason for ignoring `task_updated_date`—project label edits bump all tasks—is good for avoiding a full cache flush, but it does not make the cached rendered labels correct.

**Suggested regression test:** cache a completed task at revision T1 with label `old`, then present the same completed task at T2 after a rename/edit; assert the next fetch does not return the T1 payload.

**Suggested fix:** introduce a freshness token that represents annotation content, cache raw label IDs and resolve names against current project labels, or invalidate/rewrite affected entries on label mutations. A plain `updated_date` comparison is correct but may sacrifice the existing cache optimization.

### BR-05 — S3 basename fallback contradicts the latest-duplicate policy

**Severity: Medium (wrong image selected)**

`pick_latest_duplicate()` documents and implements lexicographic-last selection, which makes the newest `YYYY-MM` folder win (`cveta2/s3_utils.py:90`). The downloader instead calls `names_with_basename_fallback()`, whose basename alias is first-wins (`cveta2/s3_utils.py:106`). Whole-prefix listings are sorted ascending specifically before this helper is used (`cveta2/s3_utils.py:397`), so a bare request for `x.jpg` chooses `2026-01/x.jpg` over `2026-03/x.jpg`. Upload resolution uses the opposite policy.

**Suggested regression test:** force listing fallback with both monthly keys and a bare `x.jpg` request; assert the latest key is selected and that duplicate candidates produce a warning.

**Suggested fix:** group basename candidates and resolve them with `pick_latest_duplicate()`, while retaining exact full-path matches as authoritative.

### BR-06 — YOLO import ignores the YAML `path` root

**Severity: Medium (empty or incomplete conversion)**

Dataset import resolves every split as `input_dir / split_value` (`cveta2/services/convert/yolo.py:306`) and never reads `dataset.yaml`'s `path` field. The repository's own COCO fixture documents split paths as relative to `path`. A YAML stored separately from its data root therefore logs missing image directories and can produce an empty CSV. Other accepted YOLO forms mentioned by that fixture, such as image-list files or lists of paths, are also coerced into a single directory string.

**Suggested regression test:** place `dataset.yaml` in one directory, set `path` to a different dataset root, and use `train: images/train`; assert images and labels are imported from the declared root. Cover absolute roots and list-file inputs separately.

**Suggested fix:** resolve relative `path` against the YAML directory, then resolve relative split entries against that dataset root; validate and handle each supported split form explicitly.

### BR-07 — Setup commands ignore the custom projects-cache location

**Severity: Medium (cross-profile configuration corruption)**

`setup-cache --config` calls `load_projects_cache()` and `update_org_projects()` without the cache path derived from `config_path` (`cveta2/commands/setup.py:239`). `setup-clearml --config` likewise loads the default projects cache (`cveta2/commands/setup_clearml.py:23`). This conflicts with `get_projects_cache_path()`, which defines `projects.yaml` as adjacent to the selected configuration file.

A custom profile can consequently display projects from another profile and refresh the default `~/.config/cveta2/projects.yaml` instead of the selected profile's cache.

**Suggested regression test:** create different `projects.yaml` files beside default and custom configs, invoke both setup commands with the custom path, and assert only the custom project's entries are offered and updated.

**Suggested fix:** pass `get_projects_cache_path(config_path)` through every projects-cache load and update in these command flows.

### BR-08 — Malformed config YAML bypasses CLI error handling

**Severity: Medium (poor failure mode)**

`_load_raw_yaml()` calls `yaml.safe_load()` without translating `yaml.YAMLError` (`cveta2/config.py:88`). The CLI boundary catches only `Cveta2Error`, so malformed syntax exits with a PyYAML traceback rather than the project's concise user-facing error format.

**Reproduction:** point `CVETA2_CONFIG` at a file containing `cvat: [unterminated` and run `uv run cveta2 ignore --list`.

**Suggested regression test:** invoke the CLI with malformed YAML and assert a nonzero exit, a message naming the file, and no traceback.

**Suggested fix:** catch `yaml.YAMLError` at the configuration boundary and raise `Cveta2Error` with the path and parser summary. Pydantic validation errors at the same boundary should receive equivalent treatment.

### BR-09 — The Python API cannot explicitly select the personal workspace

**Severity: Medium (operations run in the wrong organization)**

`Connection.organization` distinguishes `None` from an explicit empty string, but `_open()` converts it into a `CvatConfig` that is merged using truthiness (`cveta2/api.py:153`, `cveta2/config.py:247`). Therefore `Connection(organization="")` cannot override an organization supplied by environment or file; the configured organization silently wins.

**Suggested regression test:** configure organization `team`, open with `Connection(organization="")`, and assert the constructed client targets the personal workspace.

**Suggested fix:** preserve an unset sentinel in API overrides and merge `organization` on `is not None`, not truthiness. Keep the desired empty-string representation at the client boundary.

### BR-10 — Deleted-frame count includes frames already deleted

**Severity: Low (incorrect result and redundant mutation)**

`_patch_deleted_frames()` unions requested IDs with existing deleted IDs, but always PATCHes and returns `len(frame_ids)` (`cveta2/_client_ops/task_ops.py:103`). Requesting frame 3 when frame 3 is already deleted therefore reports one frame marked and performs a no-op remote write.

**Suggested regression test:** provide `deleted_frames=[3]` and request `[3]`; assert return value zero and no API call.

**Suggested fix:** calculate `new_ids = requested - existing`, return early when empty, and report only `len(new_ids)`.

### BR-11 — Prompted upload resume emits a non-resume command

**Severity: Low (misleading recovery command)**

The reproducible-command map printed after interactive upload resolution omits `--resume` (`cveta2/commands/upload.py:159`), even though the final request preserves `args.resume` (`cveta2/commands/upload.py:197`). Copying the displayed command can start a fresh upload and create a duplicate task instead of continuing the interrupted upload.

**Suggested regression test:** invoke the prompted path with `resume=True`, capture the echoed command, and assert it contains `--resume`.

**Suggested fix:** include `"--resume": args.resume` in the echoed option map.

## Recommended fix order

1. BR-01 immediately: it crosses a filesystem trust boundary.
2. BR-02 through BR-04 next: they can silently lose or indefinitely misreport dataset content.
3. BR-05 through BR-09: correctness and configuration isolation.
4. BR-10 and BR-11: small, low-risk fixes suitable for the same maintenance cycle.

For every data-loss fix, add the regression test before changing behavior. In particular, BR-03 needs one shared definition of frame identity so downloader, partitioning, deletion, upload, and CSV behavior do not drift independently again.

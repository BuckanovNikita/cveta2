# Upload and project management

cveta2 writes to CVAT only through explicit commands. `cveta2 upload` (API
`cveta2.upload`) creates one CVAT task from a cveta2 CSV: it selects frames by label,
uploads missing images to the project's S3 cloud storage, creates the task backed by
that storage, sends box annotations, opens issues, marks deleted frames and can
complete the task. An upload records its intent in a local manifest before its first
CVAT write, so `--resume` (`resume=True`) can finish an interrupted run without
creating a second task or duplicating shapes. `cveta2 labels` (API `get_labels`,
`update_labels`) lists and edits project labels, and `cveta2 task` (API
`task_mark_deleted`, `task_drop_label`, `task_delete`, `task_set_status`) changes one
existing task. The lower-level `CvatClient` methods named below perform the same
writes for callers that build their own workflow.

Project selection (`-p` / `project=`), connection settings, retries and the
noninteractive mode are described in
[connection and configuration](connection-and-configuration.md). The CSV columns are
defined in [fetch and partition](fetch-and-partition.md); task selection by ID or name
follows the rules of `fetch-task` there.

## Upload

### Inputs

| CLI | API `upload(...)` | Meaning |
| --- | --- | --- |
| `--dataset/-d PATH` (required) | `dataset` (path or `pandas.DataFrame`) | Source rows; a file needs columns `image_name` and `instance_label` |
| `--project/-p` | `project` | Target project; prompted when omitted on the CLI |
| `--name` | `name` (required) | Task name; prompted when omitted on the CLI |
| `--labels LABEL ...` | `labels=None` | Labels that select frames; see below |
| — | `include_unannotated=False` | Also select frames whose rows have no label |
| `--in-progress PATH` | `exclude_in_progress=None` | CSV whose `image_name` values are excluded |
| `--image-dir DIR` (one) | `image_dirs=None` (list) | Extra local search roots |
| `--complete` | `complete=False` | Set every job to `acceptance` / `completed` after the upload |
| `--mark-all-deleted` | `mark_all_deleted=False` | Mark every frame of the new task deleted |
| `--resume` | `resume=False` | Continue the unfinished upload with the same intent |

Settings from the personal configuration section `upload`:

| Field | Default | Rule | Effect |
| --- | --- | --- | --- |
| `upload.images_per_job` | `100` | integer `> 0` | CVAT `segment_size`: frames per job |
| `upload.image_quality` | `100` | integer `0..100` | CVAT image chunk quality |

The API reads them from `Connection.config_path` when it is set.

### Row and frame selection

- Rows with `instance_shape="deleted"` are split off first. Their `image_name` values,
  deduplicated in CSV order, are the deleted names.
- A selected label selects frames, not rows: every row of a frame that has at least one
  row with a selected label is uploaded, including rows with labels that were not
  selected. Frames without a label row are selected only with `include_unannotated`
  (CLI: the special label `__no_annotation__`, shown in the picker as
  `(без аннотаций)`).
- CLI `--labels all` selects every dataset label plus `__no_annotation__` when the
  dataset has frames without labels, unless the dataset has a real label named `all`.
  Any other `--labels` value that is not in the dataset fails with
  `Ошибка: метки не найдены в dataset.csv: ...` followed by the available values.
- Without `--labels` the CLI shows a checkbox picker. A CSV with no labels and no
  unlabelled rows fails with
  `Ошибка: не найдено ни одного instance_label в dataset.csv.`, unless it has deleted
  rows: then the label step is skipped and only deleted frames are uploaded.
- API `labels=None` selects every dataset label and sets `include_unannotated=True`.
  API label values are not checked against the dataset; a value that matches no row
  selects nothing.
- Every `image_name` in the `--in-progress` CSV, from any of its rows, is removed from
  both the selected frames and the deleted names. An `--in-progress` file without an
  `image_name` column excludes nothing and warns; a missing file fails with
  `Ошибка: файл не найден: <path>`.
- If no selected frame and no deleted name remains, the upload fails with
  `Ошибка: после фильтрации не осталось изображений.`
- Task frames are the selected frames in CSV row order, then the deleted names that are
  not already among them. Every deleted name must therefore be available as an image.

### Validation before any external write

These checks run before any S3 or CVAT write, in this order:

1. Every selected and deleted image name must be a nonempty relative path without a
   drive prefix, an absolute root, a `..` component, a backslash or a NUL byte.
   Subfolders such as `sub/a.jpg` are allowed. Otherwise:
   `Небезопасные имена изображений: ... Загрузка не начата.`
2. Every row with a nonempty label that is not a deletion row needs all four of
   `bbox_x_tl`, `bbox_y_tl`, `bbox_x_br`, `bbox_y_br` as finite numbers. Otherwise:
   `Неполный или некорректный bbox: строка <index>, изображение '<name>', ... Загрузка не начата.`
   Box orientation and size are not checked. Empty and deletion-only inputs are valid.
3. The recovery fingerprint is computed. A value that cannot be serialized (for
   example an infinite number in another column) fails with
   `Некорректные данные изображения '<name>' для вычисления идентификатора загрузки. Загрузка не начата.`
4. The upload lock is taken and the manifest is checked (see Recovery and resume
   below).
5. Every label of the uploaded rows, including co-occurring labels, must exist in the
   project. Otherwise `LabelsMismatchError`:
   `Метки из CSV не найдены в проекте '<project>': ... Доступные метки: ....`
6. The project must have a cloud storage. Otherwise:
   `Ошибка: cloud storage не найден для проекта '<project>' (id=<id>).`
7. Every image must be found locally or already exist on S3. Otherwise:
   `Ошибка: <N> изображений нет ни локально, ни на S3: ... Задача не создана.`

### Local image lookup

Upload search roots are, in order: the explicit image directories (CLI `--image-dir`,
API `image_dirs`), then the project's image cache directory (its `image_cache` entry,
else `<cache.images_root>/<project name>`). Without any root, a warning says that only
images already on S3 are used.

For each root that exists, a name is first joined to the root directly (so subfolder
names work), then searched by basename over the whole tree. An earlier root always wins
over a later one. When one root holds several files with the basename, the
lexicographically greatest path wins and a warning lists the candidates. Absolute names
and names with `..` are never looked up. [Conversion](conversion-and-merge.md) uses
the same lookup with its own roots.

### Image upload to S3

Images always go to the project's own CVAT cloud storage (`source_storage`);
`sync_root` overrides and explicit sync roots do not apply to upload.

- The storage prefix is listed first. An image name that equals the basename of an
  existing object reuses that object's prefix-relative path; when several objects share
  the basename, the lexicographically greatest path wins with a warning. Any other name,
  including a name that contains a directory, is assigned `YYYY-MM/<image_name>` for the
  current UTC month.
- The S3 key is the prefix joined with that relative path; a relative path that itself
  starts with the prefix folder keeps every component (`images/images/a.jpg` under
  prefix `images`).
- Images found locally are uploaded unless their key already exists; objects are never
  overwritten or deleted. Transfers run in parallel up to `network.s3_workers`.
  `UploadStats` counts `uploaded`, `skipped_existing`, `failed` and `total`.
- If any transfer fails, no task is created:
  `Ошибка: <N> изображений не загрузились на S3 (s3://<bucket>/<prefix>). Задача не создана; повторите команду, уже загруженные изображения будут пропущены.`
- Request-level S3 failures carry the operation `листинг хранилища для загрузки` or
  `загрузка изображений в S3` and `s3://bucket/prefix`; how the CLI and the API report
  them is described in [images](images.md).

### Task creation and annotation writes

- The task is created with the task name, project ID and `segment_size`, then its data
  is attached as `server_files` from the cloud storage with `image_quality`,
  `use_cache=True` and `sorting_method="predefined"`, so CVAT keeps the frame order.
  The two calls are separate; the task ID is recorded between them. cveta2 waits for
  CVAT to finish processing before it continues; a processing failure raises
  `CvatApiError`.
- Frame numbers for annotations, issues and deletions come from the task's `data_meta`,
  not from the file order.
- Each labelled row with a complete box becomes one `rectangle` shape with frame, label
  ID and points `[x_tl, y_tl, x_br, y_br]`. Attributes, rotation, occlusion, z-order and
  source are not sent. Rows whose image is not in the task or whose label is not in the
  task are skipped with a warning. The shapes are sent in one create (append) request.
- Issues: rows with `issue_state` equal to `new` and nonempty `issue_text` (both
  stripped) become one open issue each, on the job that contains the frame, positioned
  at the row's box, with `issue_text` as the first comment. Rows identical in
  `image_name`, `issue_text` and box coordinates create one issue; the same text on
  different boxes creates separate issues. Rows without a complete box, with an image
  outside the task or with a frame outside every job are skipped with one warning per
  reason. Exported `open` and `resolved` states never create issues. Issues are created
  in parallel up to `network.cvat_workers`.
- Deleted frames: with `--mark-all-deleted`, every frame of the task is marked deleted;
  otherwise only the deleted names are. The write adds frames to the task's
  `deleted_frames`.
- `--complete` sets stage `acceptance` and state `completed` on every job.
- After success the task's annotation cache entry is invalidated. Upload passes no
  cloud storage to the invalidation, so its S3 step depends on `task_cache_s3`; the
  exact scope is described in [annotation cache](annotation-cache.md). An invalidation
  failure warns and does not fail the upload.

### Result

The log ends with
`Задача создана: id=..., имя=..., изображений=..., удалённых=..., аннотаций=..., issues=..., jobs≈... (segment_size=...)`
and `URL: <host>/tasks/<id>`.
The API returns `UploadResult`:

| Field | Type | Value |
| --- | --- | --- |
| `task_id` | `int` | Created or reused task |
| `task_name` | `str` | Requested name |
| `url` | `str` | `<host>/tasks/<task_id>` |
| `images` | `int` | Frames in the task |
| `deleted` | `int` | Deleted names from the CSV after exclusion (not frames marked by `--mark-all-deleted`) |
| `annotations` | `int` | Shapes sent, or verified shapes on resume |
| `issues` | `int` | Issues created by this run |

`jobs` (log only) is `ceil(images / images_per_job)`.

## Recovery and resume

### Manifest

The manifest of one upload is
`<cache base>/uploads/<server hash>/project_<id>/<fingerprint>.json`, where the cache
base is `$XDG_CACHE_HOME/cveta2` or `~/.cache/cveta2` and the server hash is the first
16 hex characters of SHA-256 of the normalized host (scheme and host lowercased, path
kept without a trailing `/`). Files are replaced atomically.

| Field | Meaning |
| --- | --- |
| `schema_version` | `3`; any other version is ignored |
| `started_at` | UTC ISO time of the first run |
| `dataset_path` | CSV path; empty for a DataFrame |
| `fingerprint` | Upload identity, also the file name |
| `project_id`, `host` | Owning project and normalized server |
| `task_name` | Requested task name |
| `cs_info` | Cloud storage chosen by the first run |
| `name_to_server_file` | Frozen image name → prefix-relative path |
| `task_image_names` | Ordered full keys bound as task frames |
| `task_id` | Created task, or `null` |
| `mapping_identity` | SHA-256 over `cs_info`, mapping and frames |
| `intent_complete` | The manifest holds the full intent |
| `creation_pending` | A create request was sent and its outcome is not known |
| `annotations_pending` | A shape write was sent and not confirmed; optional, absent means `false` |
| `completed_counts` | `[shapes, issues, jobs]` once the upload finished |

A manifest file that cannot be read or parsed, or whose host, project or fingerprint
does not match its location, is ignored.

The fingerprint is SHA-256 over the ordered frame names, the sorted deleted names, the
sorted label selection (the CLI includes `__no_annotation__` when selected), the task
name, `segment_size`, `image_quality`, `mark_all_deleted`, `complete`, and the sorted
records of every uploaded row over every column with a value, except `image_path`,
`s3_uri`, `s3_path` and `image_url`. Any change to these values is a different upload.

### Checkpoints

Required checkpoints stop the run before the next CVAT write when the manifest cannot be
saved: `Не удалось сохранить обязательное состояние загрузки (task_id=...): ... Следующая запись в CVAT не выполнена; проверьте сохранённое состояние перед продолжением.`

1. After image staging, the full intent is saved (`intent_complete=true`). Just before
   the create request it is saved again with `creation_pending=true`.
2. The task ID is saved as soon as the create request returns, before data attachment.
3. Before a shape write that sends at least one shape, `annotations_pending=true` is
   saved. After the write succeeds the mark is cleared best-effort; a failed clearing
   save only warns.
4. After all steps the counts are saved, then the manifest is deleted. A deletion
   failure warns with the successful task ID and the stale path; the upload still
   succeeds.

A CVAT create rejection with HTTP 4xx other than 408 or 429, received before a task ID
was recorded, clears `creation_pending`, so a plain rerun or `--resume` creates the
task. Any other create failure keeps the pending state.

### Lock

For the whole run the process holds a nonblocking exclusive `flock` on
`<fingerprint>.lock` beside the manifest. A second run of the same upload fails with
`UploadInProgressError`:
`Эта загрузка уже выполняется другим процессом (блокировка <path>). Дождитесь его завершения; при необходимости затем используйте --resume.`
The lock is released when the run ends or the process dies; the lock file stays. A
platform without `fcntl`, or a filesystem that refuses `flock`, runs unlocked with a
warning. Failure to open the lock file is an error.

### Run without `--resume`

- A manifest for the same fingerprint with `completed_counts` returns its stored result
  without any write and deletes the manifest.
- A manifest with a task ID or a pending create refuses the run:
  `Найдена незавершённая загрузка этого набора (задача <id>); повторное создание запрещено. Чтобы продолжить её, повторите команду с --resume. Состояние загрузки: <path>`
- Otherwise a new manifest is written and the upload proceeds.

### Run with `--resume`

1. A manifest for the same fingerprint must exist. Without one, the error lists the
   project's unfinished uploads, newest first, with dataset path, task name, image
   count, task ID and start time, and asks for the same CSV and `--labels`; with none,
   `Ошибка: незавершённых загрузок для проекта '<project>' не найдено — нечего продолжать.`
2. A manifest without the full intent, or whose `mapping_identity` does not match its
   contents, refuses: `Состояние загрузки не содержит полного намерения; продолжение небезопасно.`
3. A finished manifest returns its stored result without any CVAT or S3 write and
   deletes the manifest.
4. A pending create without a task ID refuses with
   `Результат создания задачи неизвестен; проверьте CVAT вручную. Новая задача не создаётся. Если задача не создана, удалите состояние загрузки <path> и повторите команду.`
5. The project's current cloud storage must equal the recorded one:
   `Cloud storage проекта изменён; продолжение запрещено до записи.`
6. A known task that still exists is checked before any S3 write: it must belong to
   the project, its size must equal the recorded frame count, its frame names must
   match, and its existing shapes must match the intent (below). A size or frame
   difference fails with
   `Задача <id>: кадры не совпадают или привязка ещё не завершена; запись запрещена.`;
   another project and different shapes have their own messages.
7. Images are staged again with the recorded `name_to_server_file`, so images not yet
   uploaded keep the month folder the first run chose; images already on S3 are skipped.

Then each stage is reconciled with what CVAT holds:

| Stage | Resume behavior |
| --- | --- |
| Task | A task that returns 404 is recreated: the old ID and any `annotations_pending` mark are cleared and `creation_pending` is saved before the create request, so the new task gets its shapes without the wait. Same size and matching frames: reused. Size 0: refused, the task is neither deleted nor written. Other size: refused. Another project: refused |
| Shapes | Existing shapes must equal the intended multiset of `(type, frame, label, points)` exactly, and every existing shape must have no occlusion, z-order 0, rotation 0 and no attributes. A match is reused; any difference refuses without writing |
| Pending mark | With `annotations_pending` and an empty task, the run warns, waits 30 seconds, reads the task again and sends the shapes only if it is still empty. A manifest without the mark sends to an empty task at once |
| Issues | Existing issues are read; an intended issue is skipped when an existing one has the same frame, the same first comment and a position equal within `1e-5`. Each existing issue satisfies one intended issue |
| Deleted frames, `--complete` | Repeated; both writes are idempotent |

Frame names match when they are equal in order. A remote name without a directory
matches only an intended name with the same basename that is unique among the intended
frames, and the run warns that directory identity cannot be confirmed. A remote name
with a directory may omit the cloud storage prefix.

A shape write that reaches CVAT after the 30-second wait can still duplicate shapes;
this limit is accepted.

## Labels

### `cveta2 labels`

- `--list` prints the project's labels sorted by name, one per line as
  `'<name>' (id=<id>)  цвет=<color>  атрибуты: <names>` (color and attributes only when
  present), or `Проект '<project>': нет меток`. `--list` works in noninteractive mode.
- Without `--list` an interactive menu offers add, rename, recolor, delete and done; in
  noninteractive mode it fails and suggests `--list`.
- Add: an empty name cancels; a name equal to an existing one ignoring case is refused
  with a warning. CVAT assigns the color.
- Rename: changes the name of the selected label ID; annotations keep their label. A
  name equal to another label ignoring case is refused.
- Recolor: accepts `#rrggbb` (stored lowercase); otherwise the prompt repeats
  `Введите цвет в формате #rrggbb (например, #ff0000)`.
- Delete: deletion destroys every annotation that uses the label. Before it, the
  command counts usage over all project tasks. If any selected label has a positive
  count, or any task's annotations could not be read, the user must type the selected
  label names separated by commas; a different set cancels. Otherwise a yes/no
  confirmation is asked. A count from an incomplete read is shown as
  `не менее <N>` or `число аннотаций неизвестно`.

### API

| Call | Behavior |
| --- | --- |
| `get_labels(project)` | Project labels (`LabelInfo` with `id`, `name`, `color`, `attributes`) |
| `update_labels(project, add=, rename=, delete=, recolor=)` | One project PATCH: `add` names, `rename` `{id: name}`, `delete` IDs, `recolor` `{id: "#rrggbb"}`; nothing to do sends nothing |
| `CvatClient.count_label_usage(project_id)` | `{label_id: count}` of shapes, tags and tracks |
| `CvatClient.label_usage(project_id)` | `LabelUsage(counts, skipped_task_ids)`; `complete` is true when every task was read |

Usage counting reads each task's annotations one task at a time; a task whose read
fails with a CVAT error is skipped with a warning and listed in `skipped_task_ids`.
Shapes on deleted frames are counted. A zero from an incomplete count does not prove a
label is unused.

The API and `CvatClient` apply no deletion safeguard: `update_labels(delete=...)` deletes
at once. Label edits do not invalidate the annotation cache.

## Task operations

Each `cveta2 task` subcommand takes `--project/-p` (prompted when omitted) and the
required `--task/-t` (ID or name). The API functions take `project` and `task` the same
way. The task is resolved among the project's tasks: a decimal value matches a task ID
first, then names are compared ignoring case; an ambiguous name fails and lists the
matching IDs.

Every task operation invalidates the task's annotation cache entry when it exits, also
after a failure or a declined confirmation: the local entry always, and the S3 mirror
while caching is enabled. Invalidation failures warn; see
[annotation cache](annotation-cache.md).

| CLI | API | Behavior | Returns |
| --- | --- | --- | --- |
| `task mark-deleted --frame N ... --image NAME ...` | `task_mark_deleted(project, task, frames=, images=)` | Adds frames to the task's deleted frames | Frames newly marked |
| `task drop-label --label NAME [--yes]` | `task_drop_label(project, task, label)` | Deletes the task's shapes with that label | Shapes deleted |
| `task delete [--yes]` | `task_delete(project, task)` | Deletes the task permanently | `None` |
| `task status [--stage S] [--state S]` | `task_set_status(project, task, stage=, state=)` | Patches the given fields on every job | Jobs updated |

- `mark-deleted` needs at least one frame or image:
  `Ошибка: укажите хотя бы один --frame или --image.` (API:
  `Укажите хотя бы один frame или image.`). Image names are mapped through the task's
  frame metadata; unknown names are skipped with a warning. Frame IDs outside
  `0..size-1` are skipped with a warning. Only frames not already deleted are written
  and counted; a request with nothing new writes nothing and returns `0`. Images and
  frames are applied as two writes and their counts are added.
- `drop-label` resolves the label among the task's labels by exact name; an unknown
  label fails with `Метка '<label>' не найдена в задаче <id>. Доступные метки: ...`.
  Only shapes are deleted; tags and tracks with the label remain. The CLI first counts
  the shapes: with none it reports that and writes nothing; otherwise it asks
  `Удалить <N> аннотаций с меткой '<label>' из задачи '<name>' (id=<id>)? [y/N]`.
- `delete` asks `Удалить задачу '<name>' (id=<id>) безвозвратно? [y/N]`.
- Declining a confirmation exits with `Отменено.`. `--yes/-y` skips it; in
  noninteractive mode `drop-label` and `delete` require `--yes`. The API never asks.
- `status` needs at least one of `--stage`/`--state`
  (`Ошибка: укажите хотя бы один --stage или --state.`; API:
  `Укажите хотя бы один stage или state.`). CLI values are `annotation`, `validation`,
  `acceptance` and `new`, `in-progress`, `completed`, `rejected`; `in-progress` maps to
  CVAT `in progress`. The API takes the CVAT values `cveta2.JOB_STAGES` and
  `cveta2.JOB_STATES` and rejects any other value, including `in-progress`, with
  `Cveta2Error` before contacting CVAT. Jobs are patched in parallel up to
  `network.cvat_workers`; one failed patch fails the call.

`CvatClient` exposes the same writes: `mark_frames_deleted(task_id, image_names)`,
`mark_frames_deleted_by_ids(task_id, frame_ids)`, `drop_label_annotations(task_id,
label)`, `delete_task(task_id)`, `set_task_jobs_status(task_id, stage=, state=)` and
`complete_task(task_id)` (stage `acceptance`, state `completed`). These methods do not
invalidate the cache. Every `CvatClient` write requires an open context manager.

## Command echo and compatibility

- When the CLI prompted for any input, it prints the complete command with every flag
  for a noninteractive rerun; for `upload` the echo keeps `--resume`, and for
  `drop-label`/`delete` it includes `--yes`.
- In noninteractive mode `upload` fails instead of prompting for a missing project,
  name or label selection; a CSV of only deleted rows needs no labels.
- `upload(..., resume=True)` requires the same full intent and a schema-3 manifest;
  partial or different remote annotations are never completed automatically.
- Task creation, data attachment, shape appends and deletions, issue creation, task
  deletion and label patches are non-idempotent writes; deleted-frame and job-status
  patches are idempotent. Their retry policies are described in
  [connection and configuration](connection-and-configuration.md).

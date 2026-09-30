# cveta2 output data format

cveta2 stores bbox annotations in CSV files. The record type is determined by the `instance_shape` field: `"box"` (annotation), `"none"` (image without annotations) or `"deleted"` (deleted image).

Text columns preserve their literal values when read: labels such as `"001"`
and `"NA"` remain strings. An empty CSV cell represents a missing value;
numeric and boolean columns retain their inferred types.

Only CVAT shapes of type `rectangle` become `"box"` records. Every other CVAT
shape type (`polygon`, `polyline`, `points`, …) is skipped with a warning, so a
segmentation project produces no annotation rows at all.

## Output files

### `cveta2 fetch`

| File | Description |
|---|---|
| `dataset.csv` | Data from the latest completed task for every non-deleted image |
| `obsolete.csv` | Data from stale completed tasks + data for images deleted in the latest task |
| `in_progress.csv` | Data from non-completed tasks |
| `deleted.csv` | Deleted images in the same CSV format as `dataset.csv` (`instance_shape="deleted"`) |
| `raw.csv` | (only with `--raw`) Full unprocessed CSV with all rows |

### `cveta2 fetch-task`

| File | Description |
|---|---|
| `dataset.csv` | All annotations of the selected tasks (no partitioning) |
| `deleted.csv` | Deleted images (`instance_shape="deleted"`) |

## Data format

`CvatClient.fetch_one_task()` returns `TaskAnnotations | None`; `TaskAnnotations.merge()` combines several into a `ProjectAnnotations`:

- `ProjectAnnotations` — result across all tasks: `annotations: list[AnnotationRecord]`, `deleted_images: list[DeletedImage]`
- `TaskAnnotations` — result for a single task: `task_id`, `task_name`, `annotations`, `deleted_images`. `TaskAnnotations.merge(list)` combines several tasks into a `ProjectAnnotations`

`AnnotationRecord` is either a `BBoxAnnotation` (`instance_shape="box"`) or an `ImageWithoutAnnotations` (`instance_shape="none"`). Both types contain `image_name`, `task_id`, `frame_id` and implement `to_csv_row()`.

### BBoxAnnotation

| Field | Type | Description |
|---|---|---|
| `image_name` | `str` | Image file name |
| `image_width` | `int` | Image width (px) |
| `image_height` | `int` | Image height (px) |
| `instance_shape` | `"box"` | Shape type (discriminator) |
| `instance_label` | `str` | Label name |
| `bbox_x_tl` | `float` | X of the top-left corner |
| `bbox_y_tl` | `float` | Y of the top-left corner |
| `bbox_x_br` | `float` | X of the bottom-right corner |
| `bbox_y_br` | `float` | Y of the bottom-right corner |
| `task_id` | `int` | CVAT task ID |
| `task_name` | `str` | Task name |
| `job_stage` | `str` | Review stage of the job owning the frame (`annotation`, `validation`, `acceptance`) |
| `job_state` | `str` | Review state of that job (`new`, `in progress`, `completed`, `rejected`) |
| `task_completed` | `bool \| None` | Whether every task job is finished; absent/null in legacy CSV |
| `task_updated_date` | `str` | Date/time of the task's last update. Informational only — nothing orders on it |
| `created_by_username` | `str` | Username of the annotation's author |
| `frame_id` | `int` | Frame index within the task |
| `split` | `"train" \| "val" \| "test" \| None` | Dataset split (see the note below) |
| `subset` | `str` | Subset from CVAT (task field) |
| `occluded` | `bool` | Object is occluded |
| `z_order` | `int` | Stacking order |
| `rotation` | `float` | Rotation angle (0–360) |
| `source` | `str` | Annotation source (manual/auto) |
| `annotation_id` | `int \| None` | Annotation ID in CVAT |
| `confidence` | `float \| None` | Prediction confidence (filled when converting from YOLO) |
| `issue_text` | `str` | Text of the frame's CVAT issue(s) (comments; see the note below), `""` when there are no issues |
| `issue_state` | `str` | Issue state: `open`, `resolved` or `""` (no issue); the value `new` is reserved for upload |
| `s3_image_path` | `str \| None` | Full S3 key relative to the bucket, including any subfolders of the CVAT frame name (e.g. `prefix/img.jpg`, `prefix/sub1/sub2/img.jpg`, or `prefix/2026-02/img.jpg` for new uploads), `None` when unknown. `image_name` stays a bare basename | 
| `image_path` | `str \| None` | Absolute local path to the image file, `None` when unknown |
| `attributes` | `dict[str, str]` | Custom attributes (serialized as JSON in CSV) |

> **The `split` field** is a cveta2 convention, not a CVAT one. On export from CVAT (`fetch`) it is always `None`. It is filled manually or during conversion. On upload back to CVAT (`upload`) it is ignored.

### Job stage and state (`job_stage` / `job_state`)

CVAT tracks review progress per **job**, not per task: `stage` moves
`annotation` → `validation` → `acceptance`, and `state` moves
`new` → `in progress` → `completed` (or `rejected`). A task is split into jobs
by frame range, so both columns describe the job that owns *that row's frame* —
two rows of the same task can differ when its jobs are at different points.
Both are `""` for a frame no regular annotation job covers. Ground Truth and
replica jobs do not overwrite these columns. Overlapping regular jobs prefer
an unfinished position, then the lowest job id to make ties deterministic.

**What counts as completed.** CVAT reads a job as finished when its stage is
`acceptance` *and* its state is `completed`, and a task as finished when none of
its jobs is left at annotation or validation. `fetch` applies the same rule: a
task reaches `dataset.csv` only when every job carries that pair. The
`task_completed` column preserves this result, including overlapping Ground
Truth jobs and jobs with no exported frames. An explicit false value excludes
the task even when its exported frames show completed jobs. For older CSVs
where the column is absent or null, completion falls back to the per-row job
columns, including deletion rows.
Anything else lands in `in_progress.csv`. `cveta2 task status --stage acceptance
--state completed` sets the pair on every job of a task.

**Which task wins.** When several tasks hold the same image, the one with the
highest `task_id` decides — ids are handed out in creation order and never move.
`task_updated_date` is not used for this: editing a project's labels rewrites it
on every task of the project at once, which would scramble the ordering.

The annotation cache does compare `task_updated_date`: a changed task or a
project-wide label edit invalidates the entry and fetches it again. This favors
correct rendered labels over retaining the whole project's cache after a label
change. `--no-cache` and `--force` remain available to bypass cache reads.

CVAT frame names are expected to be relative POSIX paths. Distinct images must
have unique basenames and unique stems (filenames without the final extension)
within a project or dataset, across all directories and splits. Neither two
different images named `xxx.jpg` (even in different directories) nor the pair
`xx.jpg` / `xx.png` is allowed. Repeated rows or tasks for the same image are
allowed. CSV keeps the basename in `image_name`; YOLO label filenames use the
stem. This is an input requirement; cveta2 does not guarantee automatic
detection of naming collisions.

### Issues (`issue_text` / `issue_state`)

CVAT issues are attached to a frame (image), so both columns are duplicated on all rows of the frame — both bbox rows and rows without annotations.

**On export (`fetch`):**

- The text of a single issue is its comments joined with `"; "` in creation order.
- When a frame has several issues, both columns are joined with `" | "` in the same order: the N-th fragment of `issue_text` corresponds to the N-th fragment of `issue_state` (positional alignment).
- `issue_state` takes the values `open` (unresolved), `resolved` (resolved) or `""` (no issues).
- **Caveat:** the `" | "` separator is a format convention. If a comment's text itself contains `" | "`, the column cannot be unambiguously split back into individual issues.

**On upload (`upload`):**

- Rows with `issue_state = "new"` and a non-empty `issue_text` become open issues on the created task; `issue_text` becomes the first comment.
- Each bbox gets its own issue; duplicate (`image_name`, `issue_text`, bbox coordinates) rows are created once.
- The issue position is the row's bbox; rows with `issue_text` but without all four coordinates are skipped with a warning (no full-frame issues).
- Rows with `issue_state` equal to `open`, `resolved` or `""` are ignored on upload.

### ImageWithoutAnnotations

Images without bbox annotations. They are still included in the CSV with empty bbox fields. Distinguished from `BBoxAnnotation` by `instance_shape="none"`.

| Field | Type | Description |
|---|---|---|
| `image_name` | `str` | Image file name |
| `image_width` | `int` | Image width (px) |
| `image_height` | `int` | Image height (px) |
| `instance_shape` | `"none"` | Shape type (discriminator) |
| `task_id` | `int` | CVAT task ID |
| `task_name` | `str` | Task name |
| `job_stage` | `str` | Review stage of the job owning the frame |
| `job_state` | `str` | Review state of that job |
| `task_completed` | `bool \| None` | Whether every task job is finished; absent/null in legacy CSV |
| `task_updated_date` | `str` | Date/time of the task's last update. Informational only — nothing orders on it |
| `frame_id` | `int` | Frame index within the task |
| `split` | `"train" \| "val" \| "test" \| None` | Dataset split |
| `subset` | `str` | Subset from CVAT |
| `issue_text` | `str` | Text of the frame's issue(s) (see the issues section above), `""` when there are no issues |
| `issue_state` | `str` | Issue state: `open`, `resolved` or `""` |
| `s3_image_path` | `str \| None` | Full S3 key relative to the bucket, `None` when unknown |
| `image_path` | `str \| None` | Absolute local path to the file, `None` when unknown |

### DeletedImage

Record of a deleted image. Written to `deleted.csv` with `instance_shape="deleted"` so the file shares the same column schema as `dataset.csv`.

| Field | Type | Description |
|---|---|---|
| `image_name` | `str` | Image file name |
| `image_width` | `int` | Image width (px), `0` by default |
| `image_height` | `int` | Image height (px), `0` by default |
| `instance_shape` | `"deleted"` | Shape type (discriminator) |
| `task_id` | `int` | Task ID |
| `task_name` | `str` | Task name |
| `job_stage` | `str` | Review stage of the job owning the frame |
| `job_state` | `str` | Review state of that job |
| `task_completed` | `bool \| None` | Whether every task job is finished; absent/null in legacy CSV |
| `task_updated_date` | `str` | Task update date. Informational only — nothing orders on it |
| `frame_id` | `int` | Frame index |
| `subset` | `str` | Subset from CVAT |
| `s3_image_path` | `str \| None` | Full S3 key relative to the bucket, `None` when unknown |
| `image_path` | `str \| None` | Absolute local path to the file, `None` when unknown |

### DownloadStats

| Field | Type | Description |
|---|---|---|
| `downloaded` | `int` | Number of downloaded files |
| `cached` | `int` | Skipped (already existed locally) |
| `failed` | `int` | Download errors |
| `total` | `int` | Total number of images |

### UploadStats

| Field | Type | Description |
|---|---|---|
| `uploaded` | `int` | Number of files uploaded to S3 |
| `skipped_existing` | `int` | Skipped (already existed on S3) |
| `failed` | `int` | Upload errors |
| `total` | `int` | Total number of images |

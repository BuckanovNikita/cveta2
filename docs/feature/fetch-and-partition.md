# Fetch and partition

`cveta2 fetch` exports every bounding-box annotation, unannotated frame and deleted
frame of a CVAT project and partitions the rows into `dataset.csv`, `obsolete.csv`,
`in_progress.csv` and `deleted.csv`. `cveta2 fetch-task` exports selected tasks without
partitioning. `cveta2 whats-new` lists completed tasks that a fetched `dataset.csv` does
not yet account for, and `cveta2 ignore` maintains the per-project list of tasks that
fetch skips. The Python counterparts are `cveta2.fetch`, `cveta2.fetch_task`,
`cveta2.whats_new` and `cveta2.ignore`; the lower level is `CvatClient.prepare_fetch`,
`CvatClient.fetch_one_task` and `TaskAnnotations.merge`. Fetch reads annotations through
the [annotation cache](annotation-cache.md) and downloads images as described in
[images](images.md). Project specs, retries, rate limits and server errors follow
[connection and configuration](connection-and-configuration.md).

## Commands

### `cveta2 fetch`

| Option | Effect |
| -- | -- |
| `-p`, `--project` | Project spec; without it an interactive picker opens |
| `-o`, `--output-dir` | Required output directory |
| `--raw` | Also write `raw.csv` |
| `--skip-validation` | Accept finished annotation jobs in CVAT before the export ([annotation cache](annotation-cache.md)) |
| common flags | See below |

- When the output directory exists, an interactive run asks
  `Папка <dir> уже существует. Что делать?` with `Перезаписать`, `Указать другой путь`
  and `Отмена`; `Отмена` exits with `Отменено.`. A non-interactive run logs
  `Папка <dir> уже существует — перезапись (неинтерактивный режим).` and continues.
- Writing replaces the named output files and leaves every other file in the
  directory untouched.

### `cveta2 fetch-task`

| Option | Effect |
| -- | -- |
| `-p`, `--project` | Project spec; optional when a task is given by numeric ID |
| `-t`, `--task` | Task IDs or names; `-t` without values or no `-t` opens a multi-select of the project's non-ignored tasks |
| `-o`, `--output-dir` | Required output directory; an existing directory is never prompted about |
| common flags | See below |

- Task values are stripped; blank values are dropped.
- Without `--project`, the project is the one of the first numeric task value. A task
  that belongs to no project fails with
  `Задача <id> не принадлежит ни одному проекту — укажите проект явно.`. Name-only
  values without `--project` open the project picker.
- Output is `dataset.csv` (every annotation and unannotated-frame row of the selected
  tasks) and `deleted.csv` (every deletion record of the selected tasks), with no
  partition and no deduplication.

### Common flags

| Flag | Effect |
| -- | -- |
| `--completed-only` | Keep only tasks whose CVAT task status is `completed` |
| `--no-images` | Do not download images |
| `--images-dir DIR` | Download images into `DIR` for this run |
| `--save-tasks` | Write per-task CSVs into `<output>/.tasks/` |
| `--no-cache` | Disable the annotation cache for this run |
| `--force` | Read every task from CVAT and rewrite the cache |

`--completed-only` uses the task status CVAT reports, not the job-based
`task_completed` value described below.

### Python API

`cveta2.fetch(project, output_dir, *, completed_only=False, skip_validation=False,
raw=False, images_dir=None, download_images=True, cache="use", save_tasks=False,
connection=None)` writes the same files as `cveta2 fetch` and returns `PartitionResult`.

`cveta2.fetch_task(tasks, output_dir, *, project=None, completed_only=False,
images_dir=None, download_images=True, cache="use", save_tasks=False, connection=None)`
writes the same files as `cveta2 fetch-task` and returns a `pandas.DataFrame` with
`CSV_COLUMNS` columns holding the annotation and unannotated-frame rows; deletion
records are only in `deleted.csv`.

- `cache` is `"use"` (read and write), `"refresh"` (as `--force`) or `"off"` (as
  `--no-cache`); any other value raises
  `Недопустимое значение cache=<value>; допустимые: use, refresh, off.`.
- `images_dir` together with `download_images=False` raises
  `Параметры несовместимы: передан images_dir= при download_images=False.`.
- The API never prompts: an unconfigured image directory raises `Cveta2Error`
  ([images](images.md)); `fetch_task` without `project` and without a numeric task
  raises `Не удалось определить проект: передайте project= или укажите задачи числовыми ID.`.
- Only `cveta2.fetch` accepts `skip_validation`.

## Task selection

1. Tasks on the project's ignore list are removed first. Each removed task that is not
   `silent` is logged under `Пропускаем <n> задач(а) из ignore-списка:` as
   `  - #<id> '<name>' (обновлена: <updated_date>)`.
2. Selectors resolve against the remaining tasks. A decimal selector matches a task ID
   first and otherwise a name; other selectors match names case-insensitively. Several
   name matches fail with
   `Имя задачи '<name>' неоднозначно: '<name>' (id=<id>), … Укажите числовой ID задачи.`;
   no match raises `TaskNotFoundError` (`Task not found: '<selector>'. Available tasks: …`).
   A task matched twice is kept once, in first-match order.
3. `--completed-only` is applied last.

- When every selector is a decimal ID, each task is read with one request instead of
  listing the project. The listing is used instead when a selector is unknown, belongs
  to another project or is on the ignore list. An ignored task named explicitly
  therefore fails with `TaskNotFoundError`.
- A full `fetch` always lists the project and keeps the complete, unfiltered set of
  task IDs for [annotation-cache pruning](annotation-cache.md).

## Task-by-task processing

- Selected tasks are processed concurrently, up to `network.cvat_workers` at a time.
  Results are merged in selection order, independent of completion order.
- For each task the job list is read live; frame metadata, issues and annotations come
  from CVAT or the [annotation cache](annotation-cache.md). Rate-limit, server-error
  and optional issue-read failures follow
  [connection and configuration](connection-and-configuration.md). A skipped task
  contributes no rows.
- The run logs stage wall times and one summary:
  `Обработка задач: прошло <s> с; из кэша: <n>, загружено с CVAT: <n>, пропущено: <n>, неполные issues: <n>. Суммы времени работников: …`.
  Skipped and degraded tasks are then listed as warnings
  `Пропущены задачи (<n>): [<ids>]; выгрузка неполная` and
  `Неполные issues в задачах (<n>): [<ids>]; сведения об issues отсутствуют`.
  No separate diagnostic file is written; the command still exits 0.
- No selected task logs `Нет задач для выгрузки.` and writes empty outputs.
- Order of effects: optional promotion, task selection, cache preparation, task
  processing, cache pruning (full `fetch` only), image download (when an image
  directory is set), path population, `raw.csv`, then the partition files. A failure
  before that step writes no new `raw.csv`, partition or `fetch-task` output files;
  per-task `.tasks/` files written during task processing remain.
- With `--save-tasks` (`save_tasks=True`) each task that produced annotation rows is
  written to `<output>/.tasks/task_<id>.csv` (annotation rows only). Without it
  `.tasks/` is neither created nor modified. These files are a debug artifact, not a
  resume point.

## From CVAT data to rows

### Row kinds

| `instance_shape` | Produced for |
| -- | -- |
| `box` | Each standalone `rectangle` or valid `polygon` shape, including shapes on deleted frames |
| `none` | Each frame that is not deleted and has no `box` row |
| `deleted` | Each frame listed in the task's deleted frames |

- `frame_id` is the frame's index in the task's frame metadata.
- A shape whose frame has no metadata is dropped and counted in the warning
  `Задача <id>: пропущено аннотаций без метаданных кадра: <n>`, shown on every fetch.
- A deleted frame without metadata becomes `image_name="<unknown>"` with width and
  height 0. A deleted frame with metadata carries its real width and height.
- A shape whose label ID is not a project label gets `instance_label="<unknown>"`; an
  unknown attribute spec ID becomes the attribute name.

### Task and job fields

- `task_completed` is `True` when every job of the task, including Ground Truth,
  consensus and jobs without exported frames, is at stage `acceptance` with state
  `completed`; `False` otherwise; empty when the job list is empty.
- `job_stage` / `job_state` come from the regular (`annotation`-type) job covering the
  frame. Jobs are taken in ascending ID order and a later job replaces the position only
  while the current one is `acceptance`/`completed`, so overlapping jobs prefer an
  unfinished position, then the lowest job ID. Ground Truth and other job types never
  set a position; an uncovered frame gets empty strings.
- `task_updated_date` is the task's update time, `subset` the task subset; `split` is
  always empty.

### Geometry

- A rectangle keeps its four coordinates and its `rotation`.
- A polygon becomes the axis-aligned box `(min_x, min_y, max_x, max_y)` over all
  vertices, without rounding or clipping, with `rotation=0.0`. A repeated closing vertex
  and vertices outside the image are accepted. Each conversion warns
  `Задача <task>, аннотация <id>: полигон преобразован в ограничивающий прямоугольник; это приближение исходного контура`.
- A polygon is skipped with `Задача <task>, аннотация <id>: полигон пропущен: <reason>`
  and counted in `Задача <task>: пропущено полигонов: <n>`:

  | Reason | Condition |
  | -- | -- |
  | `менее трёх пар координат` | Fewer than six coordinates |
  | `нечётное число координат` | Odd number of coordinates |
  | `нечисловые или бесконечные координаты` | A NaN or infinite coordinate |
  | `нулевая ширина ограничивающего прямоугольника` | `min_x == max_x` |
  | `нулевая высота ограничивающего прямоугольника` | `min_y == max_y` |

- Other shape types are skipped with `Skipping shape type <type> as it's not supported.`
- CVAT tracks are ignored with
  `Задача <id>: проигнорировано треков CVAT: <n>; поддерживаются только отдельные rectangle и polygon shapes`
  (`Job <id>: …` when read per job).
- When every shape of a task came from the annotation cache, its polygon and
  shape-type messages go to the debug log only; a partly cached task logs them as
  warnings for all its shapes.
- A frame whose shapes were all rejected becomes a `none` row.

### Issues

- An issue's text is its comments in creation order joined with `; `. Several issues on
  one frame are joined with ` | ` (space, vertical bar, space) in both `issue_text` and
  `issue_state`, in the same order; each state is `open` or `resolved`.
- The issue fields repeat on every `box` and `none` row of the frame. `deleted` rows
  have no issue fields. A `|` inside a comment makes splitting ambiguous.

### Identity and nested frame names

- `image_name` is the basename of the CVAT frame name. A nested name (`sub/img.jpg`) is
  kept in the internal `frame_path` field, which is not a CSV column, and is used to
  build `s3_image_path` ([images](images.md)).
- Distinct images must have unique basenames and unique stems (name without the last
  extension) across the project or dataset, in every directory and split. The same image
  may repeat across tasks and rows. This is an input requirement; fetch does not detect
  violations.

## Dataset CSV format

Every table fetch writes uses the 30 columns of `cveta2.CSV_COLUMNS`, in this order,
UTF-8 encoded, without an index column. An empty cell is a missing value.

| Column | Type | Meaning |
| -- | -- | -- |
| `image_name` | `str` | Image basename |
| `image_width` | `int` | Width in pixels |
| `image_height` | `int` | Height in pixels |
| `instance_shape` | `box` \| `none` \| `deleted` | Row kind |
| `instance_label` | `str` | Box label |
| `bbox_x_tl` | `float` | Top-left x |
| `bbox_y_tl` | `float` | Top-left y |
| `bbox_x_br` | `float` | Bottom-right x |
| `bbox_y_br` | `float` | Bottom-right y |
| `task_id` | `int` | CVAT task ID; orders recency |
| `task_name` | `str` | CVAT task name |
| `job_stage` | `str` | Stage of the regular job owning the frame, or empty |
| `job_state` | `str` | State of the regular job owning the frame, or empty |
| `task_completed` | `bool` or empty | Every job finished |
| `task_updated_date` | `str` | Task update time; informational |
| `created_by_username` | `str` | Shape author |
| `frame_id` | `int` | Frame index within the task |
| `split` | `train` \| `val` \| `test` or empty | External assignment; always empty after fetch |
| `subset` | `str` | CVAT task subset |
| `occluded` | `bool` | Occlusion flag |
| `z_order` | `int` | Stacking order |
| `rotation` | `float` | Rotation in degrees |
| `source` | `str` | CVAT annotation source |
| `annotation_id` | `int` or empty | CVAT shape ID |
| `confidence` | `float` or empty | Prediction confidence; empty after fetch |
| `issue_text` | `str` | Frame issue comments |
| `issue_state` | `str` | Frame issue states |
| `s3_image_path` | `str` or empty | Full object key in the bucket |
| `image_path` | `str` or empty | Absolute local image path |
| `attributes` | JSON object | Shape attributes, non-ASCII kept literal |

| Field group | `box` | `none` | `deleted` |
| -- | -- | -- | -- |
| Image, task, job, frame, subset, paths | Set | Set | Set |
| `instance_label`, bounding box, `created_by_username`, `occluded`, `z_order`, `rotation`, `source`, `annotation_id`, `confidence` | Set (`confidence` empty) | Empty | Empty |
| `issue_text`, `issue_state` | Set | Set | Empty |
| `split` | Empty | Empty | Empty |
| `attributes` | Shape attributes | `{}` | `{}` |

- cveta2's CSV readers keep the text columns (`image_name`, `instance_shape`,
  `instance_label`, `task_name`, `job_stage`, `job_state`, `task_updated_date`,
  `created_by_username`, `split`, `subset`, `source`, `issue_text`, `issue_state`,
  `s3_image_path`, `image_path`, `attributes`) as strings and treat only an empty cell
  as missing, so labels such as `NA` and `001` survive a round trip. Other columns keep
  pandas type inference.
- `BBoxAnnotation`, `ImageWithoutAnnotations` and `DeletedImage` are the record models
  of the three row kinds. `TaskAnnotations` holds one task's `annotations` and
  `deleted_images`; `TaskAnnotations.merge()` returns `ProjectAnnotations`.

## Partition

### Completed tasks

A task is completed when it has at least one row (annotation or deletion) and none of
its rows is unfinished. A row is finished when its `task_completed` is true; when
`task_completed` is absent or empty, the row is finished only when `job_stage` is
`acceptance` and `job_state` is `completed`. A missing stage or state is unfinished.
Rows without a usable integer `task_id` neither qualify nor disqualify a task. A task
whose completion cannot be established is treated as unfinished.

### Deciding an image

- Only completed tasks decide an image. Among an image's completed annotation rows and
  completed deletion records, the highest `task_id` wins. A deletion beats an
  annotation of the same task. Ties are broken by explicit row position, not by sort
  stability; a row without a `task_id` loses to any row with one.
- `task_updated_date` never orders the partition, because a project label edit changes
  it on every task at once.
- When the winning record is a deletion, the image is **deleted**, unless it is
  **reopened**: a newer unfinished task holds it as a live frame (a row of a task that
  did not also delete that image).
- A deleted image stays deleted when the unfinished task is older than the completed
  deletion, both annotates and deletes the frame, or only deletes it.

### Output files

| File | Contents |
| -- | -- |
| `dataset.csv` | Rows of the winning completed task for each image that is neither deleted nor reopened |
| `obsolete.csv` | Rows of older completed tasks; every row, finished or not, of deleted images; completed rows of reopened images that are not carried |
| `in_progress.csv` | Unfinished-task rows of images that are not deleted (reopened images included); for each reopened image, the carried rows of the newest completed task that holds it as a live frame; then `deleted` rows: pending deletions, then reopened deletions |
| `deleted.csv` | One deletion record per deleted image, from its winning task, sorted by image name |
| `raw.csv` (`--raw` / `raw=True`) | All annotation rows, then all deletion records, unpartitioned |

- A **pending deletion** is a deletion by an unfinished task that is not older than the
  image's completed result; with no completed result every unfinished deletion is
  pending. The image keeps its completed result until that task completes. Pending
  deletions keep their own `task_completed` (false or empty). One record per image and
  task, ordered by image then task. An unfinished deletion older than the completed
  result, and any unfinished deletion of an image that is deleted, is dropped.
- A **reopened deletion** is the winning completed deletion record of a reopened image,
  written with `task_completed=True`, so readers can tell a reopened image from a plain
  re-annotation even when no completed rows were carried.
- In `in_progress.csv` the annotation rows keep their cell text; the deletion rows are
  appended after them.
- An empty input still produces all four files with the full header.

### `PartitionResult`

| Field | Type | Contents |
| -- | -- | -- |
| `dataset` | `DataFrame` | As `dataset.csv` |
| `obsolete` | `DataFrame` | As `obsolete.csv` |
| `in_progress` | `DataFrame` | Annotation rows of `in_progress.csv` only |
| `deleted_images` | `list[DeletedImage]` | As `deleted.csv` |
| `pending_deletions` | `list[DeletedImage]` | Pending deletions |
| `reopened_deletions` | `list[DeletedImage]` | Reopened deletions (`task_completed=True`) |

## `cveta2 whats-new`

`cveta2 whats-new -d <dataset.csv> [-p <project>]` and
`cveta2.whats_new(project, dataset, *, connection=None)` list completed CVAT tasks that
the fetched files do not record as completed.

- `dataset.csv` must have `job_stage`, `job_state` and `task_id`; otherwise
  `Ошибка: в <path> отсутствуют обязательные столбцы: <columns>`. A CSV with the
  obsolete `task_status` column instead must be fetched again.
- Known tasks are the usable task IDs of `dataset.csv` and of the sibling `obsolete.csv`
  and `deleted.csv`, plus tasks whose rows in the sibling `in_progress.csv` all have an
  explicitly true `task_completed` (a boolean true or the text `true` in any case).
  A task with any unfinished row in `dataset.csv`, or in a sibling that has the
  stage/state columns, stays reportable. A sibling without those columns contributes
  its IDs only. A missing sibling is skipped; an unreadable one logs
  `<path> не прочитан (<error>) — его задачи считаются новыми` and is skipped.
- A usable task ID is a finite integral value, including numeric text; other cells name
  no task.
- The cutoff is the highest task ID among completed tasks of `dataset.csv`, or among
  all its rows when none is completed. It is informational. No usable ID fails with
  `Ошибка: столбец task_id в <path> пуст — невозможно определить задачу отсечки.`.
- The report is every project task whose CVAT task status is `completed` and whose ID
  is not known, sorted by ID. Neither `task_updated_date` nor the ignore list is used.
- The command logs `Задача отсечки (из <path>): task_id=<cutoff>`, then either
  `Новых завершённых задач в проекте '<name>' после task_id=<cutoff> не найдено` or
  `Проект '<name>': <n> задач(а) завершено после task_id=<cutoff>:` followed by
  `id=<id> <name> (updated <updated_date>)` per task.
- `whats_new` returns `WhatsNewResult` with `tasks: list[TaskInfo]` and `cutoff: int`.

## `cveta2 ignore`

An ignored task is skipped by `fetch` and `fetch-task` and appears in no output file.
The list is stored per project in the shared project configuration
(`projects.<key>.ignore`, see
[connection and configuration](connection-and-configuration.md)); each entry has `id`,
`name`, `description` and `silent`.

| Invocation | Effect |
| -- | -- |
| `--add TASK… [-d TEXT] [--silent]` | Resolve each ID or name against the project's tasks and add it |
| `--remove TASK…` | Remove entries |
| `--list` | Log every project's entries without opening a CVAT connection |
| none of the above | Interactive menu |

- `--add`, `--remove` and `--list` are mutually exclusive.
- `--add` resolves every selector before writing; an unknown selector writes nothing.
  Adding a task that is already listed warns
  `Задача '<name>' (id=<id>) уже в ignore-списке проекта '<project>' — описание и silent не изменены (используйте --remove, затем --add)`
  and keeps the existing entry.
- `--remove` drops a stored decimal ID without looking the task up in CVAT, so a task
  deleted from CVAT can still be removed; other selectors are resolved against the
  project's tasks. A resolved task that is not listed warns
  `Задача '<name>' (id=<id>) не найдена в ignore-списке проекта '<project>'`.
- `--silent` suppresses the per-fetch skip warning for that task.
- `--list` logs `Проект '<name>' (<n> задач):`, one line per entry
  (`'<name>' (id=<id>) — <description> [silent]`) and `Всего игнорируемых задач: <n>`,
  or `Ignore-списки пусты — нет игнорируемых задач ни в одном проекте`.
- `cveta2.ignore(project, *, add=None, remove=None, description="", silent=False,
  connection=None)` applies the same rules, always opens a connection to resolve the
  project, and returns the project's `IgnoredTask` entries after the change. It skips an
  already listed task on add and a resolved but unlisted task on removal silently,
  without the CLI warnings or per-entry info lines.

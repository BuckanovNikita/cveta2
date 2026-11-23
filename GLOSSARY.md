# cveta2

cveta2 turns CVAT bounding-box annotation projects into versioned training datasets: it fetches and partitions annotations into CSV, keeps local and S3 copies of images, creates CVAT tasks from CSV, verifies and prepares datasets, and publishes them to ClearML.

## Language

### Fetch and partition

**Completed task**:
A CVAT task whose every job sits at stage `acceptance` with state `completed`. Only completed tasks decide which annotation of an image is current.
_Russian_: завершённая задача
_Avoid_: finished task, accepted task, closed task

**Full fetch**:
A `fetch` of every task in a project, partitioned into the four partition outputs.
_Russian_: полная выгрузка
_Avoid_: project export, full export

**Task fetch**:
A `fetch-task` of selected tasks, which writes only `dataset.csv` and `deleted.csv`.
_Russian_: выгрузка задач
_Avoid_: partial fetch, single-task export

**Raw output**:
The `raw.csv` written by `fetch --raw`: every record, deletions included, without partitioning.
_Russian_: сырой CSV
_Avoid_: unpartitioned dataset

**Partition outputs**:
The four CSV files a full fetch writes: `dataset.csv`, `obsolete.csv`, `in_progress.csv` and `deleted.csv`.
_Russian_: файлы полной выгрузки
_Avoid_: splits (that word is reserved for train/val/test)

**Dataset (partition)**:
The rows of the latest completed task of each image that is neither deleted nor reopened; the file `dataset.csv`.
_Russian_: датасет (`dataset.csv`)
_Avoid_: набор данных, final annotations

**Obsolete**:
Rows of completed tasks that a newer completed result for the same image superseded, all rows of deleted images, and the completed rows of a reopened image other than those carried to `in_progress.csv`; the file `obsolete.csv`.
_Russian_: устаревшие аннотации (`obsolete.csv`)
_Avoid_: stale, outdated, old annotations

**In progress**:
Rows of unfinished tasks for images that are not deleted, the rows of a reopened image's newest completed task that holds it as a live frame, plus pending deletions and reopened-deletion markers; the file `in_progress.csv`.
_Russian_: в работе (`in_progress.csv`)
_Avoid_: unfinished annotations, pending annotations

**Deleted image**:
An image whose latest completed result is a deletion and that no newer unfinished task reopened; listed in `deleted.csv`.
_Russian_: удалённое изображение (`deleted.csv`)
_Avoid_: removed image, dropped frame

**Pending deletion**:
A deletion made by an unfinished task that is newer than the image's completed result; it decides nothing until its task completes.
_Russian_: отложенное удаление
_Avoid_: unconfirmed deletion, draft deletion

**Reopened deletion**:
The completed deletion record of an image that a newer unfinished task holds as a live frame again; it is written to `in_progress.csv` with `task_completed=True` and the image is in no deleted list.
_Russian_: переоткрытое удаление
_Avoid_: restored image, undeleted image

**Ignore list**:
The per-project list of task IDs that are excluded from fetch output, each with a cached name, an optional reason and an optional `silent` flag that suppresses the per-task warning.
_Russian_: список игнорируемых задач
_Avoid_: blacklist, excluded tasks, skip list

**What's-new baseline**:
What a fetched `dataset.csv` already contains, as a cutoff task ID and a set of task IDs; `whats-new` lists completed tasks beyond it.
_Russian_: точка отсчёта whats-new
_Avoid_: diff base, checkpoint

### Configuration

**Personal configuration**:
The user's own YAML file (default `~/.config/cveta2/config.yaml`, or `CVETA2_CONFIG`) holding CVAT credentials, local cache paths, network and upload settings, and a reference to the shared configuration.
_Russian_: личная конфигурация
_Avoid_: user config, local config, settings file

**Shared configuration**:
The single authoritative YAML file of a team's CVAT server, projects and managed datasets; it is never merged with personal configuration and holds no credentials or local paths.
_Russian_: общая конфигурация
_Avoid_: project config (in prose), team config, global config

**Project definition**:
A CVAT project's entry in the shared configuration: its ID, name, sync root, ignored prefix, task-cache location and ignore list.
_Russian_: описание проекта
_Avoid_: project settings

### Images and caches

**Image cache**:
The local directory where a project's images are downloaded, set per project in the `image_cache` section or falling back to `cache.images_root`.
_Russian_: кэш изображений
_Avoid_: image folder, local mirror, download dir

**Annotation cache**:
Stored annotations of CVAT jobs, one entry per task, reused while the task's update time and every job's identity, stage, state and update time are unchanged; kept locally and optionally in S3 (`task_cache_s3`).
_Russian_: кэш аннотаций
_Avoid_: task cache (in prose), fetch cache

**Sync root**:
The `s3://bucket/prefix` (or bare prefix within the project bucket) whose objects `s3-sync` copies into the image cache; when none is set, the project's cloud storage bucket and prefix are used.
_Russian_: корень синхронизации (sync root)
_Avoid_: S3 root, bucket path

**Ignored prefix**:
The leading part of S3 keys that is stripped when an image is saved locally; the rest of the key keeps its subfolders.
_Russian_: отбрасываемый префикс
_Avoid_: strip prefix, base prefix

### Task creation

**Upload manifest**:
The saved record of one unfinished `upload` (dataset, target project, task name, frame order, server file names and progress checkpoints) that lets an interrupted upload resume without creating a second task.
_Russian_: манифест загрузки
_Avoid_: upload state, upload log, journal

**Upload resume**:
A rerun of the same `upload` that continues from its upload manifest instead of starting over.
_Russian_: возобновление загрузки
_Avoid_: retry, restart

**Upload fingerprint**:
The hash of everything that changes what an `upload` does (frames in order, deleted frames, labels, annotation rows, task name, `upload` settings, `--complete` and `--mark-all-deleted`); it names the upload manifest file, so a resume finds its manifest only when all of these are the same.
_Russian_: отпечаток загрузки
_Avoid_: upload ID, checksum

### Verification

**Verification profile**:
The rule set `verify` applies to a CSV: `cveta2` or `clearml-yolo`.
_Russian_: профиль проверки
_Avoid_: mode, schema, preset

**Broken rows**:
Input rows that verification rejects, kept unchanged with their reasons; written to `broken.csv`.
_Russian_: отклонённые строки (`broken.csv`)
_Avoid_: bad rows, invalid rows, errors

**Verification report**:
The `report.json` that verification writes next to `broken.csv`, and that a prepared bundle keeps.
_Russian_: отчёт проверки (`report.json`)
_Avoid_: log, summary

**Clean CSV**:
The proposed rows after rejected rows are removed and repairs (box clipping, class canonicalization) applied; written as `clean.csv` only when cleanup is explicitly accepted.
_Russian_: очищенный CSV (`clean.csv`)
_Avoid_: fixed CSV, valid CSV

**Cleanup acceptance**:
The explicit consent (`--clean`) to drop broken rows and apply repairs; without it a result that needs cleanup is not ready.
_Russian_: подтверждение очистки
_Avoid_: auto-fix

**Blocker**:
A condition found while preparing a bundle that makes the preparation not ready (`ready: false`); it is listed under `blockers` in `report.json` and stops publication.
_Russian_: блокирующее условие
_Avoid_: blocking error, fatal issue

### Classes

**Class registry**:
The list of classes served by the class API (`api_url`), each with a number, name and flags; its fingerprint is bound into preparations.
_Russian_: реестр классов
_Avoid_: label map, class list, taxonomy

**Class identity**:
A class's registry number (`prod_id`), which stays stable while its name changes; old names are kept as aliases.
_Russian_: номер класса (`prod_id`)
_Avoid_: class ID (CVAT label id), label id

**Canonical class name**:
The current registry name of a class, to which aliases in the CSV are rewritten.
_Russian_: каноническое имя класса
_Avoid_: main name

**Empty class**:
A class marked as excluded from training; a row with it is rejected (`empty_class`).
_Russian_: исключённый класс
_Avoid_: empty label, negative class, background

### Preparation and publication

**Prepared bundle**:
A directory that preparation writes once: a copy of its source files, `broken-images.csv` and `report.json`, and, when the preparation is ready, the payload `dataset.csv`, `dataset.yaml` and `tasks.yaml` with `preparation.json` and `preparation.sha256`, which publication uploads to ClearML.
_Russian_: подготовленный датасет
_Avoid_: prepared set, release candidate, package

**Bundle preparation**:
Preparation of a prepared bundle from a full fetch directory with `verify --bundle`, with classes and image roots chosen by flags or prompts; published with `upload-dataset`.
_Russian_: ручная подготовка
_Avoid_: standalone preparation, ad hoc preparation

**Managed dataset**:
A dataset whose sources, ClearML destination, class API, S3 roots, empty classes and overlap decisions are defined by name in the shared configuration and handled by the `dataset` commands.
_Russian_: управляемый датасет
_Avoid_: configured dataset, named dataset

**Managed preparation**:
Preparation of a prepared bundle with `dataset prepare` from a user-transformed CSV and a managed fetch, bound to the managed definition and source snapshot.
_Russian_: управляемая подготовка
_Avoid_: managed build

**Source**:
One input of a managed dataset: a CVAT project (`cvat`) or an exact S3 CSV object (`s3-csv`).
_Russian_: источник
_Avoid_: input, origin, feed

**Source snapshot**:
The source evidence captured by a managed fetch (`source-snapshot.yaml`): per source the tasks with their update time and completion, the label fingerprint, the original tables or S3 object identity, and which tasks were fetched or reused. It is stored inside the published `tasks.yaml`.
_Russian_: снимок источников
_Avoid_: source evidence (in prose), snapshot alone, state dump

**Task manifest**:
The `tasks.yaml` of a prepared bundle: the task IDs included in the clean annotations and the completed tasks fully superseded by newer ones.
_Russian_: список задач датасета (`tasks.yaml`)
_Avoid_: task list file

**Stable split**:
An image's train/val/test assignment once it is published. In a managed dataset the image is identified by its content (SHA-256), and `dataset prepare` writes the published split over the user's value in every later version. Nothing assigns a split to a new image automatically.
_Russian_: стабильный split
_Avoid_: random split, rebalancing, split policy

**Overlap decision**:
A reviewed choice, for content found in several sources, of which source owns it or that it is excluded.
_Russian_: решение о пересечении
_Avoid_: dedup rule, conflict resolution

**Parent dataset**:
The latest finalized ClearML version under the same project and dataset name, which a new preparation builds on and which must not change before publication.
_Russian_: родительский датасет
_Avoid_: base dataset, previous version (in prose)

**Publication**:
The upload of a prepared bundle as a new finalized ClearML dataset version that is a child of the parent dataset, after rechecking the preparation.
_Russian_: публикация
_Avoid_: release, push, upload (reserved for CVAT task creation)

**Feedback finding**:
A verification problem traced to one frame of an original CVAT task, which `dataset report-errors` (and publication) delivers as a deduplicated CVAT review issue.
_Russian_: замечание к кадру
_Avoid_: error report, bug, comment

**Feedback receipt**:
The locally persisted record of one feedback delivery, written before the CVAT issue is created, so a rerun neither loses nor duplicates it.
_Russian_: запись о доставке замечания
_Avoid_: ack, delivery log

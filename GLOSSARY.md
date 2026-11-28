# cveta2 product glossary

Use these English and Russian terms for CVAT annotation, dataset preparation and ClearML publication. For build, test and release terminology, see the [engineering glossary](docs/adr/engineering/glossary.md).

## Language

### CVAT annotations

**Job**:
The unit of work in a CVAT task that has its own stage and state. A task can contain several jobs, so one completed job alone cannot establish task completion.
_Russian_: задание CVAT (job)

**Frame**:
One image position in a CVAT task. A frame number is local to the task, so the same image can have a different frame number in another task.
_Russian_: кадр

**Project label**:
A CVAT project's annotation category, with an ID and a name. Renaming the label preserves its ID and existing annotations.
_Russian_: метка проекта

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
A fetch of selected tasks by ID or name. Its main outputs are `dataset.csv` and `deleted.csv`, with optional per-task tables.
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

**Dataset draft**:
The `dataset.yaml` a full fetch writes next to the partition outputs: the ClearML destination, output URI, class API, excluded class numbers and image roots known from the global configuration, each key optional; `verify` reads it instead of the configuration.
_Russian_: черновик `dataset.yaml`
_Avoid_: template, stub config

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

**Task without data**:
A CVAT task to which no data has been uploaded yet; CVAT answers reads of its data with `400 Data is not uploaded for the task yet`. Every fetch skips it with a notice: it contributes no rows, is never cached, and is read normally once its data is uploaded.
_Russian_: задача без данных
_Avoid_: empty task (an empty task has data but no annotations)

**What's-new baseline**:
The set of task IDs already accounted for by a fetched dataset and its available sibling tables, together with a cutoff ID for reporting. A task with CVAT status `completed` is new when its ID is absent from the set, even below the cutoff.
_Russian_: точка отсчёта whats-new
_Avoid_: diff base, checkpoint

### Configuration

**Personal configuration**:
The user's own YAML file (default `~/.config/cveta2/config.yaml`, or `CVETA2_CONFIG`) holding CVAT credentials, local cache paths, network and upload settings, a reference to the global configuration and, when the team allows them, local overrides.
_Russian_: личная конфигурация
_Avoid_: user config, local config, settings file

**Local override**:
A per-project option in the personal configuration (`overrides.projects.<key>`) that replaces the global value for that user; allowed only when the global configuration sets `local_overrides: true`. Overridable: publication settings only.
_Russian_: локальное переопределение
_Avoid_: personal override, shadow setting

**Global configuration**:
The single authoritative YAML file of a team's CVAT server, projects, publication settings and managed datasets, selected by `--global-config`, `CVETA2_GLOBAL_CONFIG` or `global_config`; it holds no credentials or local paths.
_Russian_: общая конфигурация
_Avoid_: shared configuration (former name), project config (in prose), team config

**Project definition**:
A CVAT project's entry in the global configuration: its CVAT ID, sync root, ignored prefix, task-cache location, ignore list and optional publication settings.
_Russian_: описание проекта
_Avoid_: project settings

**Publication settings**:
The optional `publication` block of a project definition: the ClearML destination (`clearml.project`, `clearml.dataset`, optional `clearml.output_uri`), the class API (`api_url`), excluded classes (`empty_classes`) and S3 image roots (`s3_roots`) used to publish that project's bundles.
_Russian_: настройки публикации
_Avoid_: release settings, ClearML config

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

### Merge and detection formats

**Merge conflict**:
An image name present in both input CSVs. All annotation rows for that image come from the winning input.
_Russian_: конфликт при объединении

**Negative image**:
A retained training image with no annotated object. In a cveta2 detection CSV it can be represented by a row with `instance_shape=none`, and in a YOLO dataset by an empty label file.
_Russian_: изображение без аннотаций

**Class index**:
The number assigned to a label in a detection export. YOLO and COCO export build the mapping from the input CSV's box labels across all splits. The class registry has its own numbering.
_Russian_: индекс класса

**Split**:
An image's assignment to the training (`train`), validation (`val`) or test (`test`) subset of a dataset.
_Russian_: выборка (split)

### Verification

**Verification profile**:
The rule set `verify` applies to a CSV: `cveta2` or `clearml-yolo`.
_Russian_: профиль проверки
_Avoid_: mode, schema, preset

**Image quarantine**:
Rejection of an entire image group when a malformed record makes its remaining rows unreliable. In the cveta2 profile the group is scoped by image name and task ID when available.
_Russian_: отклонение всей группы строк изображения

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
Consent to drop broken rows and apply repairs. Bundle preparation (`verify <directory>`) and managed preparation (`dataset prepare`) accept cleanup by default, and `--no-clean` opts out. The CSV check (`verify <file>`) keeps it opt-in with `--clean`. Without it, a result that needs cleanup is not ready.
_Russian_: подтверждение очистки
_Avoid_: auto-fix

**Blocker**:
A condition that stops a preparation from writing its payload (`ready: false`), listed under `blockers` in `report.json`. In bundle preparation: structural CSV errors, no valid image, needed cleanup with `--no-clean`, a non-excluded class without a bbox, or failure to derive the task manifest ([preparation logic](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/cveta2/application/use_cases/dataset_bundle.py#L208-L226)); split conditions that publication will enforce later are listed under `pending`. In managed preparation: the same conditions except the task-manifest error, and also one image content in two splits.
_Russian_: блокирующее условие
_Avoid_: blocking error, fatal issue

### Classes

**Class registry**:
The list of classes served by the class API (`api_url`), each with a number, name, threshold and optional flags (a missing flag reads as false).
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
A preparation directory containing source evidence and diagnostics. When preparation succeeds it also contains the editable publication payload: `dataset.csv`, `dataset.yaml` and `tasks.yaml`. See the [dataset format](docs/dataset-format.md) for the files in each workflow.
_Russian_: подготовленный датасет
_Avoid_: prepared set, release candidate, package

**Bundle preparation**:
Preparation of a prepared bundle from a full fetch directory with `verify <directory>`, taking the destination, class API, excluded classes and image roots from flags, the dataset draft and the parent dataset, with cleanup accepted by default; published with `upload-dataset`.
_Russian_: подготовка каталога
_Avoid_: standalone preparation, ad hoc preparation

**Managed dataset**:
A dataset whose sources, ClearML destination, class API, S3 roots, empty classes and overlap decisions are defined by name in the global configuration and handled by the `dataset` commands.
_Russian_: управляемый датасет
_Avoid_: configured dataset, named dataset

**Managed fetch**:
The collection of a named managed dataset's CVAT and S3 CSV sources. Its outputs include the source tables and the source snapshot used by managed preparation.
_Russian_: выгрузка управляемого датасета

**Transformed CSV**:
The user's edited or combined annotation table passed to managed preparation together with its managed fetch.
_Russian_: преобразованный CSV

**Managed preparation**:
Preparation of a prepared bundle with `dataset prepare` from a user-transformed CSV and a managed fetch, using the managed definition and the source snapshot as they are when each command runs.
_Russian_: управляемая подготовка
_Avoid_: managed build

**Source**:
One input of a managed dataset: a CVAT project (`cvat`) or an exact S3 CSV object (`s3-csv`).
_Russian_: источник
_Avoid_: input, origin, feed

**Source snapshot**:
The source evidence captured by a managed fetch (`source-snapshot.yaml`): the CVAT server and organization it was fetched from; per source the tasks with their update time and completion, the label fingerprint, the original tables or S3 object identity, and which tasks were fetched, reused or skipped as tasks without data. It is stored inside the published `tasks.yaml`.
_Russian_: снимок источников
_Avoid_: source evidence (in prose), snapshot alone, state dump

**Task manifest**:
The `tasks.yaml` of a prepared bundle: the task IDs included in the clean annotations and the completed tasks fully superseded by newer ones.
_Russian_: список задач датасета (`tasks.yaml`)
_Avoid_: task list file

**Pending split**:
An image assignment that still needs a split before publication. Preparation can write a payload while the assignment is pending.
_Russian_: незаполненный split

**Stable split**:
An image’s published split, carried into later versions unless the user explicitly resplits it. Bundle preparation identifies the image by name, and managed preparation identifies it by content.
_Russian_: стабильный split
_Avoid_: random split, rebalancing, split policy

**Overlap decision**:
A reviewed choice, for content found in several sources, of which source owns it or that it is excluded.
_Russian_: решение о пересечении
_Avoid_: dedup rule, conflict resolution

**Parent dataset**:
The latest finalized ClearML version under the same project and dataset name, which a new preparation builds on and which must not change before publication. For a managed dataset it must be a managed version, unless the preparation starts a managed lineage.
_Russian_: родительский датасет
_Avoid_: base dataset, previous version (in prose)

**Managed lineage**:
The chain of managed versions of one managed dataset, each published with the previous one as its parent. It starts in a ClearML dataset with no versions, or with `dataset prepare --first`, which publishes a first version with no parent over versions without managed metadata.
_Russian_: управляемая история
_Avoid_: adoption, migration

**Publication**:
The upload of a prepared bundle as a new finalized ClearML dataset version that is a child of the parent dataset (the first version of a managed lineage has none), after validating the directory's current files; `upload-dataset` publishes four files, `dataset publish` three.
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

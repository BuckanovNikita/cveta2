# Python API

## Функции-команды (рекомендуемый способ)

Модуль `cveta2` предоставляет функции верхнего уровня, повторяющие data-команды CLI (интерактивные `setup`/`setup-cache`/`doctor` аналогов не имеют). Они выполняют весь конвейер и записывают **те же самые** CSV-файлы, что и CLI. `fetch` возвращает `PartitionResult` со всеми четырьмя частями разбиения, `fetch_task` — все выгруженные строки одним `pandas.DataFrame` (колонки — `cveta2.CSV_COLUMNS`, см. [контракт датасета](../specs/001-project-documentation/contracts/dataset-format.md)).

```python
import cveta2

# Выгрузка проекта: пишет dataset/obsolete/in_progress/deleted CSV в out/,
# возвращает PartitionResult (dataset / obsolete / in_progress / deleted_images)
result = cveta2.fetch("my-project", output_dir="out")
print(result.dataset)  # DataFrame актуальных аннотаций
print(len(result.obsolete))  # устаревшие строки тоже доступны

# Кэш аннотаций: cache="use" (по умолчанию) / "refresh" (= --force) / "off" (= --no-cache)
result = cveta2.fetch("my-project", output_dir="out", cache="refresh")

# Принять завершённую разметку в CVAT и выгрузить завершённые задачи
result = cveta2.fetch(
    "my-project", output_dir="out", skip_validation=True, completed_only=True
)

# Выгрузка отдельных задач (по ID или имени) — DataFrame без разбиения
df = cveta2.fetch_task([456, "Партия 3"], output_dir="out", project="my-project")

# project= можно опустить, если задачи заданы числовыми ID —
# проект определяется по первой такой задаче
df = cveta2.fetch_task([456], output_dir="out")

# Загрузка датасета обратно в CVAT (labels=None → все кадры)
result = cveta2.upload("out/dataset.csv", "my-project", "Партия 4")
print(result.task_id, result.url, result.annotations, result.issues)

# Конвертация форматов
cveta2.convert_to_yolo("out/dataset.csv", "yolo_out/")
cveta2.convert_from_yolo(
    "preds/",
    "predicted.csv",
    names_file="classes.yaml",
    image_dirs=["/mnt/data/images"],
)
cveta2.convert_to_coco("out/dataset.csv", "coco_out/")

# Прочие операции
cveta2.merge("old/dataset.csv", "new/dataset.csv", "merged.csv")
news = cveta2.whats_new("my-project", "out/dataset.csv")
for task in news.tasks:  # news.cutoff — task_id отсечки (int)
    print(task.id, task.name)
stats = cveta2.s3_sync(
    "my-project", "/mnt/data/my-project"
)  # синхронизация изображений из S3
labels = cveta2.get_labels("my-project")
cveta2.update_labels("my-project", add=["cat", "dog"])

# Ignore-список задач (как `cveta2 ignore`)
entries = cveta2.ignore("my-project", add=[456], description="Дубликаты", silent=True)
entries = cveta2.ignore("my-project")  # только показать текущие записи
cveta2.ignore("my-project", remove=[456])

# Операции над задачами
cveta2.task_mark_deleted("my-project", task=456, images=["img003.jpg"])
cveta2.task_drop_label("my-project", task=456, label="cat")
cveta2.task_set_status("my-project", task=456, state="completed")
cveta2.task_delete("my-project", task=456)
```

`task_set_status` принимает **значения CVAT**, а не значения CLI:
`stage` — одно из `cveta2.JOB_STAGES` (`annotation`, `validation`,
`acceptance`), `state` — одно из `cveta2.JOB_STATES` (`new`, `in progress`,
`completed`, `rejected`). Обратите внимание на `in progress` **с пробелом**:
в CLI тот же статус пишется через дефис (`--state in-progress`), и перенос
дефисной формы в Python-вызов приведёт к `Cveta2Error`.

Только `cveta2.fetch` принимает keyword-only `skip_validation=False`.
При `True` перед чтением аннотаций он изменяет в CVAT jobs
`annotation`/`completed` на `acceptance`/`completed`, если непустой полный
список jobs задачи состоит только из этих двух завершённых сочетаний.
Ground Truth, реплики и jobs без выгружаемых кадров тоже участвуют в проверке.
Задачи из ignore-списка исключены; jobs на других stage/state не изменяются,
а уже принятые jobs не обновляются. После принятия заново читается статус
задач, включая отбор `completed_only=True` в том же запуске.

Перед первым обновлением сбрасывается настроенный локальный кэш задачи и,
при включённом кэшировании, S3-зеркало. Ошибка проверки, сброса или обновления
поднимает `Cveta2Error` до выгрузки аннотаций и публикации результатов.
Успешные изменения CVAT не откатываются; повторный вызов обновляет только
оставшиеся jobs. Подробнее о сбросе при `cache="off"` — в
[документации кэша](images-and-cache.md#кэш-аннотаций-задач).

Спецификация проекта во всех функциях — ID, имя или строка `"org/имя"` (`"/имя"` — личное пространство): префикс организации переопределяет организацию из конфига, как и в CLI.

Все функции, обращающиеся к CVAT, принимают необязательный параметр `connection=` — объект `cveta2.Connection` с полями `host`, `username`, `password`, `organization`, `config_path`. Не заданные поля берутся в порядке: переменные окружения → `~/.config/cveta2/config.yaml` → встроенный пресет. **API никогда не спрашивает интерактивно** — при отсутствии настроек поднимается `MissingHostError` / `MissingCredentialsError`. Чтобы переиспользовать одно соединение для нескольких вызовов, передайте `Connection(client=...)` с уже открытым `CvatClient` (вне контекстного менеджера клиент отклоняется с понятной ошибкой).

```python
import cveta2

result = cveta2.fetch(
    "my-project",
    output_dir="out",
    connection=cveta2.Connection(
        host="https://app.cvat.ai",
        username="bot",
        password="secret",
    ),
)
```

Параметры `upload`: `labels=None` загружает все кадры (и включает кадры без аннотаций), список меток `labels=[...]` отбирает кадры по меткам (со всеми сопутствующими метками этих кадров), `include_unannotated=True` дополнительно включает кадры без аннотаций.

## Продвинутый уровень: `CvatClient`

`CvatClient` даёт низкоуровневый доступ к CVAT для сценариев, которых нет среди функций-команд. Для любых обращений к серверу он **требует** контекстного менеджера (`with ... as client:`) и, как и функции API, **не спрашивает** учётные данные интерактивно — при их отсутствии поднимается `MissingCredentialsError`. Интерактивные промпты живут только в CLI.

```python
from cveta2 import CvatClient, TaskAnnotations

# Конфигурация загружается автоматически (env, config file, preset)
with CvatClient() as client:
    # Выгрузка идёт по задачам: prepare_fetch отбирает их, fetch_one_task
    # читает одну. Те же фильтры, что у CLI-команд fetch / fetch-task.
    ctx = client.prepare_fetch(123, completed_only=True)

    # Только конкретные задачи — по ID или имени (список)
    ctx = client.prepare_fetch(123, task_selector=[456, "Партия 3"])

    per_task = [
        r
        for task in ctx.tasks
        if (r := CvatClient.fetch_one_task(client.api, task, ctx)) is not None
    ]
    result = TaskAnnotations.merge(per_task)

    # result.annotations — список BBoxAnnotation и ImageWithoutAnnotations
    for ann in result.annotations[:3]:
        print(
            f"{ann.image_name}: {ann.instance_label} "
            f"[{ann.bbox_x_tl}, {ann.bbox_y_tl}, {ann.bbox_x_br}, {ann.bbox_y_br}]"
        )

    # result.deleted_images — список DeletedImage
    for img in result.deleted_images:
        print(f"Удалено: {img.image_name} (task={img.task_id})")

# Явная конфигурация (если нужны нестандартные настройки)
from cveta2 import CvatConfig

cfg = CvatConfig.load()
with CvatClient(cfg) as client:
    tasks = client.list_project_tasks(123)
```

Для обычной выгрузки этот уровень не нужен: `cveta2.fetch(...)` и
`cveta2.fetch_task(...)` делают то же самое и сразу пишут CSV.

## Работа с проектами

```python
from cveta2 import CvatClient

with CvatClient() as client:
    # Список проектов
    projects = client.list_projects()
    for p in projects:
        print(f"{p.id}: {p.name}")

    # Разрешить имя проекта → ID
    project_id = client.resolve_project_id("Мой проект")

    # Список задач проекта
    tasks = client.list_project_tasks(project_id)
    for t in tasks:
        print(f"{t.id}: {t.name} ({t.status})")
```

## Управление метками

```python
from cveta2 import CvatClient

with CvatClient() as client:
    project_id = client.resolve_project_id("Мой проект")

    # Получить метки проекта
    labels = client.get_project_labels(project_id)
    for label in labels:
        print(f"{label.id}: {label.name} ({label.color})")

    # Подсчитать использование меток (количество аннотаций)
    usage = client.count_label_usage(project_id)
    for label in labels:
        count = usage.get(label.id, 0)
        print(f"{label.name}: {count} аннотаций")

    # Добавить новые метки
    client.update_project_labels(project_id, add=["cat", "dog"])

    # Переименовать метку (по label_id)
    client.update_project_labels(project_id, rename={1: "кошка"})

    # Изменить цвет метки
    client.update_project_labels(project_id, recolor={1: "#ff0000"})

    # Удалить метку (НЕОБРАТИМО уничтожает все аннотации с этой меткой)
    client.update_project_labels(project_id, delete=[1])
```

## Создание задачи и загрузка аннотаций

```python
from pathlib import Path
import pandas as pd
from cveta2 import CvatClient

with CvatClient() as client:
    project_id = client.resolve_project_id("Мой проект")

    # Определить cloud storage проекта
    cs_info = client.detect_project_cloud_storage(project_id)
    print(f"Cloud storage: s3://{cs_info.bucket}/{cs_info.prefix}")

    # Создать задачу с изображениями из cloud storage
    task_id = client.create_upload_task(
        project_id=project_id,
        name="Партия 3",
        image_names=["img001.jpg", "img002.jpg", "img003.jpg"],
        cloud_storage_id=cs_info.id,
        segment_size=100,
    )
    print(f"Задача создана: id={task_id}")

    # Загрузить bbox-аннотации из DataFrame
    df = pd.read_csv("output/dataset.csv")
    num_shapes = client.upload_task_annotations(task_id=task_id, annotations_df=df)
    print(f"Загружено аннотаций: {num_shapes}")

    # Пометить фреймы как удалённые
    deleted_count = client.mark_frames_deleted(
        task_id=task_id,
        image_names={"img003.jpg"},
    )
    print(f"Помечено удалёнными: {deleted_count}")

    # Завершить задачу (все jobs → stage=acceptance, state=completed)
    jobs_updated = client.complete_task(task_id)
    print(f"Завершено jobs: {jobs_updated}")
```

## Загрузка и синхронизация изображений

```python
from pathlib import Path
from cveta2 import CvatClient, TaskAnnotations

with CvatClient() as client:
    project_id = client.resolve_project_id("Мой проект")

    # Скачать изображения по результатам выгрузки. download_images ждёт
    # ProjectAnnotations — тот же объект, что собирает пример выше.
    # project_id обязателен: без него cloud storage проекта не определяется
    # и все изображения попадут в счётчик ошибок.
    ctx = client.prepare_fetch(project_id)
    result = TaskAnnotations.merge(
        [
            r
            for task in ctx.tasks
            if (r := CvatClient.fetch_one_task(client.api, task, ctx)) is not None
        ]
    )
    stats = client.download_images(
        result, Path("/mnt/data/my-project"), project_id=project_id
    )
    print(
        f"Загружено: {stats.downloaded}, из кэша: {stats.cached}, ошибок: {stats.failed}"
    )

    # Синхронизировать все изображения из S3 (без привязки к аннотациям)
    cs_info = client.detect_project_cloud_storage(project_id)
    stats = client.sync_project_images(
        project_id=project_id,
        target_dir=Path("/mnt/data/my-project"),
        project_cloud_storage=cs_info,
    )
    print(f"Синхронизировано: {stats.downloaded} новых, {stats.cached} уже было")
```


## Совместимость операций

Выбор неоднозначного имени проекта или задачи вызывает `Cveta2Error` с подходящими ID; используйте числовой ID в нужной организации. `ignore(..., remove=[ID])` удаляет сохранённую запись без поиска удалённой задачи. Ошибки учётных данных учитывают `Connection.config_path`.

`upload(..., resume=True)` требует полного совпадения намерения и современного манифеста; частичные или отличающиеся удалённые аннотации не дополняются автоматически. Повторный `convert_to_coco` заменяет только файлы, принадлежащие предыдущему экспорту по его метаданным. Подробности перехода описаны в [CLI](cli.md).

## Проверка CSV и явная публикация

Эти операции не используют подключение к CVAT. `verify` проверяет путь к CSV;
`verify_dataframe` проверяет DataFrame без изменения исходного объекта.
`schema_for(profile)` возвращает схему для `cveta2` или `clearml-yolo`.
`ValidationOptions` содержит `iou_threshold=0.99`, `check_images=False`,
`image_root=None`, `base_dir=None`, `emit_warnings=True`. Относительные пути
image_path разрешаются относительно входного CSV (для DataFrame — base_dir
или текущей директории); image_root дополняет только пустой image_path.

```python
import cveta2

options = cveta2.ValidationOptions(check_images=True, iou_threshold=0.99)
report = cveta2.verify(
    "export/dataset.csv",
    profile="cveta2",
    options=options,
    output_dir="inspection",
    clean=False,
)
print(report.is_valid, report.requires_cleanup)
print(report.broken_row_positions, report.issues)
schema = cveta2.schema_for("clearml-yolo")
# frame — уже загруженный DataFrame; индекс не заменяет позицию строки
report = cveta2.verify_dataframe(frame, profile="cveta2", options=options)
```

`ValidationResult` содержит предлагаемые `clean`, исходные отклонённые `broken`,
позиции `clean_row_positions`/`broken_row_positions` с нуля, все `issues`,
`checked_checks`, `skipped_checks`, `structural_errors` и счётчики строк/изображений.
`is_valid` описывает исходный ввод; `requires_cleanup` отдельно отмечает отклонения
или предлагаемые исправления. `reasons_for(position)` возвращает причины для
позиции, `warnings` — предупреждения. Ни результат проверки, ни наличие `clean`
не означают согласия на очистку. Только `clean=True` разрешает записать `clean.csv`;
для этого нужен новый `output_dir`. Структурные ошибки очистить нельзя.

```python
import cveta2

options = cveta2.PrepareOptions(
    project="CV/datasets",
    dataset_name="reviewed",
    api_url="https://classes.example.org/api/classes",
    local_roots=("/data/images",),
    s3_roots=("s3://images/project",),
    class_empty={17: True},
    accept_default_classes=True,
    accept_class_changes=True,
    clean=False,
)
try:
    prepared = cveta2.prepare_dataset(
        "export",
        output_dir="prepared",
        options=options,
    )
except cveta2.MissingDecisions as error:
    for decision in error.decisions:
        print(decision.kind, decision.message, decision.choices)
```

`prepare_dataset` принимает директорию полной выгрузки с четырьмя исходными CSV.
`PrepareOptions` явно задаёт destination project, dataset name, публичный API
классов, независимые корни, решения empty и принятие изменений; по умолчанию оба
`accept_*` и `clean` равны `False`. API никогда не спрашивает пользователя:
отсутствующие решения возвращаются в `MissingDecisions.decisions`.
Разбиение назначается снаружи, медиа проверяются всегда. `PreparedDataset` содержит
`directory`, `ready`, `validation`, `metadata`, `tasks`; только `ready=True`
разрешает последующую загрузку. При замечаниях изучите отчёт, исправьте вход или
явно разрешите очистку и подготовьте новую директорию.

После отдельного просмотра подготовленной директории выполните:

```python
import cveta2

publication = cveta2.upload_dataset("prepared")
print(publication.dataset_id, publication.version)
```

`upload_dataset(prepared_dir)` повторяет полную проверку неизменности и доступности
и возвращает `Publication` только после финализации. Он не выполняет очистку.
Публикуются ровно три payload-файла; CVAT-функция `cveta2.upload` остаётся отдельной.
Ошибки операций относятся к `Cveta2Error`; известный ID созданной дочерней версии
сохраняется в сообщении при последующем сбое. Точный порядок, состав пакета и
действия при несовпадении описаны в [CLI](cli.md#опубликовать-подготовленный-пакет-cveta2-upload-dataset)
и [контракте](../specs/001-project-documentation/contracts/dataset-format.md#verification-and-prepared-bundles).

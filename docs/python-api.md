# Python API

## Функции-команды (рекомендуемый способ)

Модуль `cveta2` предоставляет функции верхнего уровня, повторяющие data-команды CLI (интерактивные `setup`/`setup-cache`/`setup-clearml`/`doctor` аналогов не имеют). Они выполняют весь конвейер и записывают **те же самые** CSV-файлы, что и CLI. `fetch` возвращает `PartitionResult` со всеми четырьмя частями разбиения, `fetch_task` — все выгруженные строки одним `pandas.DataFrame` (колонки — `cveta2.CSV_COLUMNS`, см. DATASET_FORMAT.md).

```python
import cveta2

# Выгрузка проекта: пишет dataset/obsolete/in_progress/deleted CSV в out/,
# возвращает PartitionResult (dataset / obsolete / in_progress / deleted_images)
result = cveta2.fetch("my-project", output_dir="out")
print(result.dataset)  # DataFrame актуальных аннотаций
print(len(result.obsolete))  # устаревшие строки тоже доступны

# Кэш аннотаций: cache="use" (по умолчанию) / "refresh" (= --force) / "off" (= --no-cache)
result = cveta2.fetch("my-project", output_dir="out", cache="refresh")

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


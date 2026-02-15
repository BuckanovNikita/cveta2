# cveta2

Утилита для работы с аннотациями CVAT-проектов: выгрузка (`cveta2 fetch`), создание задач с переносом аннотаций (`cveta2 upload`), синхронизация изображений (`cveta2 s3-sync`). Доступна как CLI и как Python API (`CvatClient`, `fetch_annotations`).

## Что умеет

- Собирает **все bbox-аннотации** проекта в плоский список — одна запись на каждый bounding box
- Возвращает **список удалённых изображений** по всем задачам проекта
- **Автоматически разделяет** результат на актуальный датасет, устаревшие данные и данные в работе
- **Скачивает изображения** из S3 cloud storage, подключённого к CVAT (boto3, с кэшированием)
- **Создаёт задачи в CVAT** из `dataset.csv` — загружает изображения на S3, создаёт задачу с cloud storage и автоматически переносит bbox-аннотации
- Поддерживает фильтр по задачам со статусом `completed`
- Всё за один вызов — без промежуточных XML/ZIP файлов

## Установка

```bash
pip install cveta2-0.1.0-py3-none-any.whl
```

## Быстрый старт

1. Запустите интерактивную настройку:

```bash
cveta2 setup
```

2. Выгрузите проект:

```bash
# По ID проекта
cveta2 fetch --project 123 -o output/

# По имени проекта
cveta2 fetch --project "Мой проект" -o output/

# Интерактивный выбор проекта из списка
cveta2 fetch -o output/
```

В папке `output/` появятся файлы:

| Файл | Описание |
|---|---|
| `dataset.csv` | Данные из последней завершённой задачи для каждого неудалённого изображения |
| `obsolete.csv` | Данные из старых завершённых задач + данные для изображений, удалённых в последней задаче |
| `in_progress.csv` | Данные из незавершённых задач |
| `deleted.txt` | Имена изображений, удалённых в их последней задаче (по одному на строку) |
| `raw.csv` | (только с `--raw`) Полный необработанный CSV со всеми строками |

## Загрузка изображений из S3

При `fetch` cveta2 автоматически скачивает изображения проекта из S3 cloud storage, подключённого к CVAT. Cloud storage определяется из метаданных задач (`source_storage`).

### Где хранятся изображения

Для каждого проекта вы задаёте директорию вручную — либо при `cveta2 setup`, либо при первом `fetch`. Пути хранятся в конфиге:

```yaml
image_cache:
  coco8-dev: /mnt/disk01/data/project_coco_8_dev
  my-other-project: /home/user/datasets/other
```

Изображения сохраняются прямо в указанную директорию (`/mnt/disk01/data/project_coco_8_dev/image.jpg`), без дополнительных подпапок.

### S3-креды

Для загрузки используется `boto3` со стандартной цепочкой авторизации — `~/.aws/credentials`, переменные `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, IAM-роли. В конфиге cveta2 S3-креды не хранятся.

### Управление загрузкой

```bash
# Обычный fetch — изображения скачиваются (путь из конфига или интерактивный ввод)
cveta2 fetch -p coco8-dev -o output/

# Пропустить загрузку изображений
cveta2 fetch -p coco8-dev -o output/ --no-images

# Указать/переопределить директорию для изображений на этот запуск
cveta2 fetch -p coco8-dev -o output/ --images-dir /tmp/my-images
```

Уже скачанные файлы не загружаются повторно.

### Неинтерактивный режим и изображения

В неинтерактивном режиме (`CVETA2_NO_INTERACTIVE=true`) если путь для изображений не настроен — `fetch` завершается с ошибкой. Решение: укажите `--images-dir`, `--no-images`, или добавьте `image_cache.<project>` в конфиг.

## Конфигурация

### Файл конфигурации

По умолчанию используется `~/.config/cveta2/config.yaml`. Создать его проще всего через `cveta2 setup`.

Пример с токеном:

```yaml
cvat:
  host: "https://app.cvat.ai"
  organization: "my-team"
  token: "your-personal-access-token"
```

Пример с логином/паролем:

```yaml
cvat:
  host: "https://app.cvat.ai"
  organization: "my-team"
  username: "your-username"
  password: "your-password"
```

Полный пример конфига со всеми секциями:

```yaml
cvat:
  host: "https://app.cvat.ai"
  organization: "my-team"
  token: "your-personal-access-token"

image_cache:
  coco8-dev: /mnt/disk01/data/project_coco_8_dev
  my-other-project: /home/user/datasets/other

upload:
  images_per_job: 100
```

### Пресет по умолчанию

cveta2 содержит встроенный пресет (`cveta2/presets/default.yaml`), который задаёт `host: http://localhost:8080`. Если вы работаете с локальным CVAT — достаточно добавить только креды.

### Приоритет источников

1. **Переменные окружения** — переопределяют файл и пресет
2. **Файл конфигурации** (`~/.config/cveta2/config.yaml`)
3. **Встроенный пресет** — базовые значения по умолчанию
4. **Интерактивный ввод** — если не указаны логин/пароль/токен

### Переменные окружения

| Переменная | Описание |
|---|---|
| `CVAT_HOST` | URL сервера CVAT |
| `CVAT_ORGANIZATION` | Slug организации CVAT |
| `CVAT_TOKEN` | Personal Access Token |
| `CVAT_USERNAME` | Имя пользователя |
| `CVAT_PASSWORD` | Пароль |
| `CVETA2_CONFIG` | Путь к файлу конфигурации (по умолчанию `~/.config/cveta2/config.yaml`) |
| `CVETA2_NO_INTERACTIVE` | Установите `true`, чтобы отключить все интерактивные промпты (см. ниже) |
| `CVETA2_DATA_TIMEOUT` | Таймаут (в секундах) ожидания обработки данных при создании задачи через `upload` (по умолчанию `60`) |

### Неинтерактивный режим

Для использования в CI/скриптах установите `CVETA2_NO_INTERACTIVE=true`. В этом режиме:

- Все интерактивные промпты заменяются на ошибки с подсказкой, какой флаг или переменную окружения нужно использовать
- Команда `setup` недоступна — настраивайте через env-переменные или редактируя файл конфигурации напрямую
- При `fetch` без `--project` — ошибка (укажите `-p`)
- Если не хватает учётных данных — ошибка (задайте `CVAT_TOKEN` или `CVAT_USERNAME`/`CVAT_PASSWORD`)
- Если путь к изображениям не настроен — ошибка (укажите `--images-dir`, `--no-images` или `image_cache` в конфиге)
- Если выходная директория уже существует — перезаписывается без вопросов
- Команда `upload` недоступна — выбор классов требует интерактивного режима

Переменная может быть не установлена вообще — по умолчанию интерактивный режим включён.

```bash
# Пример CI-использования
export CVAT_HOST="https://app.cvat.ai"
export CVAT_TOKEN="your-token"
export CVETA2_NO_INTERACTIVE=true

cveta2 fetch -p 123 -o output/ --images-dir /data/images
```

## Команды CLI

### `cveta2 setup`

Интерактивный мастер настройки подключения к CVAT: хост, авторизация (токен или логин/пароль), пути для кэша изображений. Результат сохраняется в `~/.config/cveta2/config.yaml`.

```bash
cveta2 setup

# Указать другой путь к конфигу
cveta2 setup --config /path/to/config.yaml
```

### `cveta2 fetch`

Выгрузка bbox-аннотаций и удалённых изображений из проекта CVAT. Результат разбивается на три CSV-файла + список удалённых.

```bash
# По ID проекта
cveta2 fetch --project 123 -o output/

# По имени проекта
cveta2 fetch -p "Имя проекта" -o output/

# Интерактивный выбор проекта (из кэша; в списке есть опция обновить с CVAT)
cveta2 fetch -o output/

# Дополнительно сохранить полный (необработанный) CSV
cveta2 fetch -p 123 -o output/ --raw

# Только задачи со статусом completed
cveta2 fetch -p 123 -o output/ --completed-only

# Без загрузки изображений
cveta2 fetch -p 123 -o output/ --no-images

# С указанием директории для изображений
cveta2 fetch -p "coco8-dev" -o output/ --images-dir /mnt/data/coco8
```

### `cveta2 s3-sync`

Синхронизация изображений из S3 cloud storage в локальный кэш для всех настроенных в `image_cache` проектов. Скачивает только отсутствующие файлы — никогда не загружает и не удаляет ничего на S3.

```bash
# Синхронизировать все настроенные проекты
cveta2 s3-sync

# Только один конкретный проект
cveta2 s3-sync -p coco8-dev
```

### `cveta2 upload`

Создание задачи в CVAT из `dataset.csv`: интерактивный выбор классов, загрузка изображений на S3 и создание задачи с cloud storage. Bbox-аннотации из CSV автоматически переносятся в новую задачу (фрейм-маппинг читается из CVAT `data_meta`, а не из порядка файлов).

```bash
# Минимальный вызов — проект и CSV обязательны
cveta2 upload -p "Мой проект" -d output/dataset.csv

# По ID проекта
cveta2 upload -p 123 -d output/dataset.csv

# Исключить изображения, которые уже в работе
cveta2 upload -p "Мой проект" -d output/dataset.csv --in-progress output/in_progress.csv

# Указать директорию с изображениями и имя задачи
cveta2 upload -p "Мой проект" -d output/dataset.csv --image-dir /mnt/data --name "Партия 3"

# Интерактивный выбор проекта (без -p)
cveta2 upload -d output/dataset.csv
```

Процесс:
1. Чтение `dataset.csv` и (опционально) `in_progress.csv` для исключения занятых изображений
2. Интерактивный выбор классов (`instance_label`) через checkbox — изображения без аннотаций тоже можно включить
3. Загрузка недостающих изображений на S3 (уже загруженные пропускаются)
4. Создание задачи в CVAT с cloud storage и автоматическим разбиением на jobs
5. Загрузка bbox-аннотаций в новую задачу (привязка по `image_name` → `frame_id` из CVAT)

Количество изображений на job настраивается через `upload.images_per_job` в конфиге (по умолчанию 100). Таймаут ожидания обработки данных CVAT — через переменную `CVETA2_DATA_TIMEOUT` (по умолчанию 60 секунд).

### `cveta2 doctor`

Диагностика конфигурации и окружения. Проверяет:

- Наличие и корректность файла конфигурации (хост, креды)
- Доступность AWS/S3-учётных данных (boto3)
- Group-права на директории кэша изображений (чтобы все пользователи группы имели доступ)

```bash
cveta2 doctor
```

## Примеры использования

```bash
# Путь к конфигу через env (кэш проектов — projects.yaml в той же папке)
CVETA2_CONFIG=/path/to/config.yaml cveta2 fetch -p 123 -o output/
```

## Python API

### Выгрузка аннотаций

```python
from cveta2 import CvatClient, fetch_annotations
from cveta2.config import CvatConfig

# Конфиг загрузится из файла и env (или выполните cveta2 setup)
cfg = CvatConfig.load()

# Для загрузки изображений нужен контекстный менеджер
with CvatClient(cfg) as client:
    result = client.fetch_annotations(project_id=123, completed_only=True)

    # Скачать изображения из S3 в указанную директорию
    from pathlib import Path
    stats = client.download_images(result, Path("/mnt/data/my-project"))
    print(f"Загружено: {stats.downloaded}, из кэша: {stats.cached}, ошибок: {stats.failed}")

# Или короче через функцию-обёртку: сразу DataFrame
df = fetch_annotations(project_id=123, cfg=cfg)
print(df.head())

# Аннотации bbox — список BBoxAnnotation
for ann in result.annotations[:3]:
    print(
        f"{ann.image_name}: {ann.instance_label} "
        f"[{ann.bbox_x_tl}, {ann.bbox_y_tl}, {ann.bbox_x_br}, {ann.bbox_y_br}] "
        f"author={ann.created_by_username}"
    )

# Удалённые изображения — список DeletedImage
for img in result.deleted_images:
    print(f"Удалено: {img.image_name} (task={img.task_id}, frame={img.frame_id})")
```

### Создание задачи и загрузка аннотаций

```python
from pathlib import Path
from cveta2 import CvatClient
from cveta2.config import CvatConfig

cfg = CvatConfig.load()

with CvatClient(cfg) as client:
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
        segment_size=100,  # изображений на job
    )
    print(f"Задача создана: id={task_id}")

    # Загрузить bbox-аннотации из DataFrame
    import pandas as pd
    df = pd.read_csv("output/dataset.csv")
    num_shapes = client.upload_task_annotations(task_id=task_id, annotations_df=df)
    print(f"Загружено аннотаций: {num_shapes}")
```

## Формат данных

`CvatClient.fetch_annotations()` возвращает `ProjectAnnotations`:

- `annotations: list[BBoxAnnotation]`
- `deleted_images: list[DeletedImage]`
- `images_without_annotations: list[ImageWithoutAnnotations]`

### BBoxAnnotation

| Поле | Тип | Описание |
|---|---|---|
| `image_name` | `str` | Имя файла изображения |
| `image_width` | `int` | Ширина изображения (px) |
| `image_height` | `int` | Высота изображения (px) |
| `instance_shape` | `"box"` | Тип фигуры (всегда `"box"`) |
| `instance_label` | `str` | Название метки |
| `bbox_x_tl` | `float` | X верхнего левого угла |
| `bbox_y_tl` | `float` | Y верхнего левого угла |
| `bbox_x_br` | `float` | X нижнего правого угла |
| `bbox_y_br` | `float` | Y нижнего правого угла |
| `task_id` | `int` | ID задачи в CVAT |
| `task_name` | `str` | Название задачи |
| `task_status` | `str` | Статус задачи (completed, annotation, ...) |
| `task_updated_date` | `str` | Дата/время последнего обновления задачи |
| `created_by_username` | `str` | Имя пользователя, создавшего аннотацию |
| `frame_id` | `int` | Индекс кадра внутри задачи |
| `subset` | `str` | Подмножество (train/val/test/default) |
| `occluded` | `bool` | Объект перекрыт |
| `z_order` | `int` | Порядок наложения |
| `rotation` | `float` | Угол поворота (0–360) |
| `source` | `str` | Источник аннотации (manual/auto) |
| `annotation_id` | `int \| None` | ID аннотации в CVAT |
| `attributes` | `dict[str, str]` | Пользовательские атрибуты |

### DeletedImage

| Поле | Тип | Описание |
|---|---|---|
| `task_id` | `int` | ID задачи |
| `task_name` | `str` | Название задачи |
| `task_status` | `str` | Статус задачи |
| `task_updated_date` | `str` | Дата обновления задачи |
| `frame_id` | `int` | Индекс кадра |
| `image_name` | `str` | Имя файла изображения |

### DownloadStats

| Поле | Тип | Описание |
|---|---|---|
| `downloaded` | `int` | Количество скачанных файлов |
| `cached` | `int` | Пропущено (уже существовали локально) |
| `failed` | `int` | Ошибки при скачивании |
| `total` | `int` | Общее количество изображений |

### UploadStats

| Поле | Тип | Описание |
|---|---|---|
| `uploaded` | `int` | Количество загруженных файлов на S3 |
| `skipped_existing` | `int` | Пропущено (уже существовали на S3) |
| `failed` | `int` | Ошибки при загрузке |
| `total` | `int` | Общее количество изображений |

## Тесты и фикстуры CVAT

Тесты в `tests/test_cvat_fixtures.py` проверяют фикстуры проекта `coco8-dev`: загрузку JSON и соответствие данных именам задач (например, задача `all-removed` — все кадры в `deleted_frames`, `normal` — есть кадры не в удалённых).

Фикстуры лежат в `tests/fixtures/cvat/coco8-dev/` (`project.json` и `tasks/*.json`). Чтобы пересоздать их из реального CVAT:

```bash
export CVAT_HOST="http://localhost:8080"  # или ваш URL CVAT
export CVAT_USERNAME="admin"
export CVAT_PASSWORD="ваш_пароль"
uv run python scripts/export_cvat_fixtures.py --project coco8-dev
```

По умолчанию вывод пишется в `tests/fixtures/cvat/coco8-dev/`. Другой каталог: `--output-dir path`. Подробнее — в `scripts/README.md`.

Для тестов можно собирать **фейковые проекты** из базовых фикстур: произвольный набор задач в любом порядке, с повторами, случайными или заданными именами и статусами. Модуль `tests/fixtures/fake_cvat_project.py`: `FakeProjectConfig` (pydantic) и `build_fake_project(base_fixtures, config)`. Пример: три задачи «normal» подряд с id 100, 101, 102 или случайный набор из 5 задач с `count=5`, `seed=42`. Тесты — в `tests/test_fake_cvat_project.py`.

## Ограничения

- Извлекаются только фигуры типа `rectangle` (в выходе это `instance_shape="box"`). Другие типы фигур CVAT (`polygon`, `polyline`, `points` и т.д.) пропускаются.

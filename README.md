# cveta2

`cveta2` - утилита для выгрузки аннотаций из CVAT-проектов в удобные Pydantic-модели.
Можно использовать как CLI (`cveta2 fetch`), как Python API (`CvatClient`) и как функцию-обертку (`fetch_annotations`).

## Что умеет

- Собирает все `bbox` аннотации проекта в плоский список `BBoxAnnotation`
- Возвращает список удаленных кадров/изображений как `DeletedImage`
- Автоматически разделяет результат на три CSV: актуальный датасет, устаревшие данные и данные в работе
- Поддерживает фильтр по задачам со статусом `completed`
- Работает через конфиг: env-переменные и/или YAML (рекомендуется `cveta2 setup`)

## Установка

```bash
uv sync
```

## Быстрый старт

1. Запустите интерактивную настройку:

```bash
uv run cveta2 setup
```

2. Выгрузите проект (можно указать ID, имя проекта или запустить без `--project` — откроется выбор из списка):

```bash
uv run cveta2 fetch --project 123 -o output/
# или по имени проекта:
uv run cveta2 fetch --project "Мой проект" -o output/
# или интерактивный выбор проекта:
uv run cveta2 fetch -o output/
```

В папке `output/` появятся три CSV-файла (`dataset.csv`, `obsolete.csv`, `in_progress.csv`) и `deleted.txt`.

Список проектов кэшируется в `projects.yaml` рядом с конфигом; в интерактивном режиме можно нажать `0`, чтобы обновить список с CVAT.

## Конфигурация

По умолчанию используется `~/.config/cveta2/config.yaml`.

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

### Приоритет источников

1. Переменные окружения (`CVAT_HOST`, `CVAT_ORGANIZATION`, `CVAT_TOKEN`, `CVAT_USERNAME`, `CVAT_PASSWORD`) переопределяют файл.
2. YAML-конфиг по умолчанию: `~/.config/cveta2/config.yaml` (путь можно задать через `CVETA2_CONFIG`).
3. Если хост не задан — выводится подсказка: выполните `cveta2 setup` или задайте env.
4. Интерактивный ввод (если не хватает кредов и токен не задан) при первом запросе к API.

## CLI: примеры

Сначала настройте доступ: `uv run cveta2 setup` или задайте переменные окружения (см. Конфигурация).

```bash
# Базовый fetch — результат в папку output/
uv run cveta2 fetch --project 123 -o output/
uv run cveta2 fetch -p "Имя проекта" -o output/

# Интерактивный выбор проекта (из кэша; 0 — обновить список с CVAT)
uv run cveta2 fetch -o output/

# Дополнительно сохранить полный (необработанный) CSV
uv run cveta2 fetch -p 123 -o output/ --raw

# Обрабатывать только задачи со статусом completed
uv run cveta2 fetch -p 123 -o output/ --completed-only

# Путь к конфигу через env (кэш проектов будет в той же папке: projects.yaml)
CVETA2_CONFIG=/path/to/config.yaml uv run cveta2 fetch -p 123 -o output/

# Вариант запуска как модуля
uv run python -m cveta2 fetch -p 123 -o output/
```

### Выходные файлы

| Файл | Описание |
|---|---|
| `dataset.csv` | Данные из последней завершённой задачи для каждого неудалённого изображения |
| `obsolete.csv` | Данные из старых завершённых задач + данные для изображений, удалённых в последней задаче |
| `in_progress.csv` | Данные из незавершённых задач |
| `deleted.txt` | Имена изображений, удалённых в их последней задаче (по одному на строку) |
| `raw.csv` | (только с `--raw`) Полный необработанный CSV со всеми строками |

## Python API

```python
from cveta2 import CvatClient, fetch_annotations
from cveta2.config import CvatConfig

# Конфиг из файла + env (или задайте CVAT_HOST, CVAT_TOKEN в окружении)
cfg = CvatConfig.load()

client = CvatClient(cfg)
result = client.fetch_annotations(project_id=123, completed_only=True)

# Альтернатива через функцию-обертку:
# result = fetch_annotations(project_id=123, cfg=cfg, completed_only=True)

for ann in result.annotations[:3]:
    print(
        f"{ann.image_name}: {ann.instance_label} "
        f"[{ann.bbox_x_tl}, {ann.bbox_y_tl}, {ann.bbox_x_br}, {ann.bbox_y_br}] "
        f"author={ann.created_by_username}"
    )

for img in result.deleted_images:
    print(f"Удалено: {img.image_name} (task={img.task_id}, frame={img.frame_id})")
```

## Формат результата

`fetch` возвращает `ProjectAnnotations`:

- `annotations: list[BBoxAnnotation]`
- `deleted_images: list[DeletedImage]`

### Поля `BBoxAnnotation`

| Поле | Тип | Описание |
|---|---|---|
| `image_name` | `str` | Имя файла изображения |
| `image_width` | `int` | Ширина изображения в пикселях |
| `image_height` | `int` | Высота изображения в пикселях |
| `instance_shape` | `"box"` | Тип фигуры (всегда `"box"`) |
| `instance_label` | `str` | Название метки |
| `bbox_x_tl` | `float` | X верхнего левого угла |
| `bbox_y_tl` | `float` | Y верхнего левого угла |
| `bbox_x_br` | `float` | X нижнего правого угла |
| `bbox_y_br` | `float` | Y нижнего правого угла |
| `task_id` | `int` | ID задачи CVAT |
| `task_name` | `str` | Название задачи |
| `task_status` | `str` | Статус задачи |
| `task_updated_date` | `str` | Дата/время последнего обновления задачи |
| `created_by_username` | `str` | Имя пользователя, создавшего аннотацию (если доступно) |
| `frame_id` | `int` | Индекс кадра внутри задачи |
| `subset` | `str` | Подмножество задачи (`train`, `val`, `test`, `default`, ...) |
| `occluded` | `bool` | Признак перекрытия объекта |
| `z_order` | `int` | Порядок наложения |
| `rotation` | `float` | Угол поворота |
| `source` | `str` | Источник аннотации (`manual`, `auto`, ...) |
| `annotation_id` | `int \| None` | ID аннотации в CVAT |
| `attributes` | `dict[str, str]` | Пользовательские атрибуты |

### Поля `DeletedImage`

| Поле | Тип | Описание |
|---|---|---|
| `task_id` | `int` | ID задачи |
| `task_name` | `str` | Название задачи |
| `task_status` | `str` | Статус задачи |
| `task_updated_date` | `str` | Дата/время последнего обновления задачи |
| `frame_id` | `int` | Индекс удаленного кадра |
| `image_name` | `str` | Имя файла изображения |

## Важные ограничения

- Сейчас извлекаются только фигуры типа `rectangle` (в выходе это `instance_shape="box"`).
- Другие типы фигур CVAT (`polygon`, `polyline`, `points` и т.д.) пропускаются.
# cveta2

Утилита для получения аннотаций из проектов CVAT. Доступна как CLI и как Python-API через класс `CvatClient` (полный структурированный результат) и функцию-обёртку `fetch_annotations` (готовый `pandas.DataFrame`).

## Возможности

- Получение **всех bounding-box аннотаций** проекта в плоском формате (одна запись на каждый bbox)
- Получение **списка удалённых изображений** по всем задачам проекта
- **Автоматическое разделение** результата на актуальный датасет, устаревшие данные и данные в работе
- Всё за **один вызов** — без промежуточных XML/ZIP файлов
- **Конфигурация через файл** — настройки CVAT хранятся в `~/.config/cveta2/config.yaml`

## Установка

```bash
uv sync
```

## Быстрая настройка

Самый простой способ начать — запустить интерактивную настройку:

```bash
uv run cveta2 setup
```

Команда задаст несколько вопросов (адрес сервера, способ аутентификации) и сохранит конфигурацию в `~/.config/cveta2/config.yaml`.

Если конфиг уже существует, текущие значения будут предложены по умолчанию — можно просто нажать Enter, чтобы оставить их.

## Конфигурация

### Файл конфигурации

Создайте файл `~/.config/cveta2/config.yaml` (или используйте `cveta2 setup`):

```yaml
cvat:
  host: "https://app.cvat.ai"
  organization: "my-team"
  token: "your-personal-access-token"
```

Или с логином/паролем:

```yaml
cvat:
  host: "https://app.cvat.ai"
  organization: "my-team"
  username: "your-username"
  password: "your-password"
```

### Приоритет настроек

Настройки загружаются из нескольких источников (в порядке приоритета):

1. **CLI-аргументы** (`--host`, `--organization`, `--token` и т.д.) — наивысший приоритет
2. **Переменные окружения** (`CVAT_HOST`, `CVAT_ORGANIZATION`, `CVAT_TOKEN` и т.д.)
3. **Файл конфигурации** (`~/.config/cveta2/config.yaml`)
4. **Интерактивный ввод** — если не указаны логин/пароль/токен

### Переменные окружения

| Переменная     | Описание                          |
|----------------|-----------------------------------|
| `CVAT_HOST`    | URL сервера CVAT                  |
| `CVAT_ORGANIZATION` | Slug организации CVAT      |
| `CVAT_TOKEN`   | Personal Access Token             |
| `CVAT_USERNAME`| Имя пользователя                  |
| `CVAT_PASSWORD`| Пароль                            |

## Использование

### CLI

```bash
# Первоначальная настройка
uv run cveta2 setup

# Базовый fetch — результат в папку output/
uv run cveta2 fetch -p 123 -o output/

# Дополнительно сохранить полный (необработанный) CSV
uv run cveta2 fetch -p 123 -o output/ --raw

# Только задачи со статусом «completed»
uv run cveta2 fetch -p 123 -o output/ --completed-only

# Указать альтернативный конфиг-файл через env
CVETA2_CONFIG=/path/to/config.yaml uv run cveta2 fetch -p 123 -o output/

# Также работает как python-модуль
uv run python -m cveta2 fetch -p 123 -o output/
```

### Как Python-библиотека

```python
from cveta2 import CvatClient, fetch_annotations
from cveta2.config import CvatConfig

# Конфиг загрузится из файла и env (или выполните cveta2 setup)
cfg = CvatConfig.load()

client = CvatClient(cfg)
result = client.fetch_annotations(project_id=123)

# Или короче через функцию-обёртку: сразу DataFrame с аннотациями
df = fetch_annotations(project_id=123, cfg=cfg)
print(df.head())

# Аннотации bbox — список BBoxAnnotation
for ann in result.annotations:
    print(f"{ann.image_name}: {ann.instance_label} [{ann.bbox_x_tl}, {ann.bbox_y_tl}, {ann.bbox_x_br}, {ann.bbox_y_br}]")

# Удалённые изображения — список DeletedImage
for img in result.deleted_images:
    print(f"Удалено: {img.image_name} (task {img.task_id})")
```

## Формат данных

### BBoxAnnotation

| Поле             | Тип          | Описание                                    |
|------------------|--------------|---------------------------------------------|
| `image_name`     | `str`        | Имя файла изображения                       |
| `image_width`    | `int`        | Ширина изображения (px)                      |
| `image_height`   | `int`        | Высота изображения (px)                      |
| `instance_shape` | `"box"`      | Тип фигуры (всегда `"box"`)                 |
| `instance_label` | `str`        | Название метки                               |
| `bbox_x_tl`     | `float`      | X верхнего левого угла                       |
| `bbox_y_tl`     | `float`      | Y верхнего левого угла                       |
| `bbox_x_br`     | `float`      | X нижнего правого угла                       |
| `bbox_y_br`     | `float`      | Y нижнего правого угла                       |
| `task_id`        | `int`        | ID задачи в CVAT                             |
| `task_name`      | `str`        | Название задачи                              |
| `task_status`    | `str`        | Статус задачи (completed, annotation, …)     |
| `frame_id`       | `int`        | Индекс кадра внутри задачи                   |
| `subset`         | `str`        | Подмножество (train/val/test/default)        |
| `occluded`       | `bool`       | Объект перекрыт                              |
| `z_order`        | `int`        | Порядок наложения                            |
| `rotation`       | `float`      | Угол поворота (0–360)                        |
| `source`         | `str`        | Источник аннотации (manual/auto)             |
| `annotation_id`  | `int \| None`| ID аннотации в CVAT                         |
| `attributes`     | `dict`       | Пользовательские атрибуты                    |

### DeletedImage

| Поле         | Тип   | Описание                  |
|--------------|-------|---------------------------|
| `task_id`    | `int` | ID задачи                 |
| `task_name`  | `str` | Название задачи           |
| `task_status` | `str` | Статус задачи            |
| `task_updated_date` | `str` | Дата обновления задачи |
| `frame_id`   | `int` | Индекс кадра              |
| `image_name` | `str` | Имя файла изображения     |

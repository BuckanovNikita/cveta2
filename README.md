# cveta2

`cveta2` - утилита для выгрузки аннотаций из CVAT-проектов в удобные Pydantic-модели.
Можно использовать как CLI (`cveta2 fetch`), как Python API (`CvatClient`) и как функцию-обертку (`fetch_annotations`).

## Что умеет

- Собирает все `bbox` аннотации проекта в плоский список `BBoxAnnotation`
- Возвращает список удаленных кадров/изображений как `DeletedImage`
- Отдает результат сразу в JSON (и при желании сохраняет CSV/TXT)
- Поддерживает фильтр по задачам со статусом `completed`
- Работает через единый конфиг: CLI аргументы + env + YAML

## Установка

```bash
uv sync
```

## Быстрый старт

1. Запустите интерактивную настройку:

```bash
uv run cveta2 setup
```

2. Выгрузите проект:

```bash
uv run cveta2 fetch --project-id 123 -o result.json
```

Если `--output` не передан, JSON печатается в `stdout`.

## Конфигурация

По умолчанию используется `~/.config/cveta2/config.yaml`.

Пример с токеном:

```yaml
cvat:
  host: "https://app.cvat.ai"
  token: "your-personal-access-token"
```

Пример с логином/паролем:

```yaml
cvat:
  host: "https://app.cvat.ai"
  username: "your-username"
  password: "your-password"
```

### Приоритет источников

1. CLI аргументы (`--host`, `--token`, `--username`, `--password`)
2. Переменные окружения (`CVAT_HOST`, `CVAT_TOKEN`, `CVAT_USERNAME`, `CVAT_PASSWORD`)
3. YAML-конфиг (`~/.config/cveta2/config.yaml`)
4. Интерактивный ввод (если не хватает кредов и токен не задан)

## CLI: примеры

```bash
# Базовый fetch (host/creds берутся из env или config)
uv run cveta2 fetch --project-id 123

# Явно передать host + токен
uv run cveta2 fetch --host https://app.cvat.ai --project-id 123 --token YOUR_TOKEN

# Сохранить JSON в файл
uv run cveta2 fetch --project-id 123 -o result.json

# Дополнительно сохранить все bbox в CSV
uv run cveta2 fetch --project-id 123 --annotations-csv annotations.csv

# Дополнительно сохранить только имена удаленных изображений (по одному на строку)
uv run cveta2 fetch --project-id 123 --deleted-txt deleted.txt

# Обрабатывать только задачи со статусом completed
uv run cveta2 fetch --project-id 123 --completed-only

# Использовать альтернативный конфиг
uv run cveta2 fetch --project-id 123 --config /path/to/config.yaml

# Вариант запуска как модуля
uv run python -m cveta2 fetch --project-id 123
```

## Python API

```python
from cveta2 import CvatClient, fetch_annotations
from cveta2.config import CvatConfig

cfg = CvatConfig.load(cli_host="https://app.cvat.ai", cli_token="your-token")

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
  token: "your-personal-access-token"
```

Или с логином/паролем:

```yaml
cvat:
  host: "https://app.cvat.ai"
  username: "your-username"
  password: "your-password"
```

### Приоритет настроек

Настройки загружаются из нескольких источников (в порядке приоритета):

1. **CLI-аргументы** (`--host`, `--token` и т.д.) — наивысший приоритет
2. **Переменные окружения** (`CVAT_HOST`, `CVAT_TOKEN` и т.д.)
3. **Файл конфигурации** (`~/.config/cveta2/config.yaml`)
4. **Интерактивный ввод** — если не указаны логин/пароль/токен

### Переменные окружения

| Переменная     | Описание                          |
|----------------|-----------------------------------|
| `CVAT_HOST`    | URL сервера CVAT                  |
| `CVAT_TOKEN`   | Personal Access Token             |
| `CVAT_USERNAME`| Имя пользователя                  |
| `CVAT_PASSWORD`| Пароль                            |

## Использование

### CLI

```bash
# Первоначальная настройка
uv run cveta2 setup

# Если host указан в конфиге — достаточно project-id
uv run cveta2 fetch --project-id 123

# Явный host и токен через CLI
uv run cveta2 fetch --host https://app.cvat.ai --project-id 123 --token YOUR_TOKEN

# Сохранить в файл
uv run cveta2 fetch --project-id 123 -o result.json

# Сохранить аннотации в CSV и имена удалённых изображений в текстовый файл
uv run cveta2 fetch --project-id 123 --annotations-csv annotations.csv --deleted-txt deleted.txt

# Только задачи со статусом «completed»
uv run cveta2 fetch --project-id 123 --completed-only

# Указать альтернативный конфиг-файл
uv run cveta2 fetch --project-id 123 --config /path/to/config.yaml

# Также работает как python-модуль
uv run python -m cveta2 fetch --project-id 123
```

### Как Python-библиотека

```python
from cveta2 import CvatClient, fetch_annotations
from cveta2.config import CvatConfig

# Конфиг загрузится из файла + env автоматически
cfg = CvatConfig.load(cli_host="https://app.cvat.ai", cli_token="your-token")

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
| `frame_id`   | `int` | Индекс кадра              |
| `image_name` | `str` | Имя файла изображения     |

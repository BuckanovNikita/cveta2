# cveta2

Утилита для получения аннотаций из проектов CVAT в виде структурированных Python-объектов (Pydantic-моделей).

## Возможности

- Получение **всех bounding-box аннотаций** проекта в плоском формате (одна запись на каждый bbox)
- Получение **списка удалённых изображений** по всем задачам проекта
- Всё за **один вызов** — без промежуточных XML/ZIP файлов
- **Конфигурация через файл** — настройки CVAT хранятся в `~/.config/cveta2/config.toml`

## Установка

```bash
uv sync
```

## Быстрая настройка

Самый простой способ начать — запустить интерактивную настройку:

```bash
uv run cveta2 setup
```

Команда задаст несколько вопросов (адрес сервера, способ аутентификации) и сохранит конфигурацию в `~/.config/cveta2/config.toml`.

Если конфиг уже существует, текущие значения будут предложены по умолчанию — можно просто нажать Enter, чтобы оставить их.

## Конфигурация

### Файл конфигурации

Создайте файл `~/.config/cveta2/config.toml` (или используйте `cveta2 setup`):

```toml
[cvat]
host = "https://app.cvat.ai"
token = "your-personal-access-token"
```

Или с логином/паролем:

```toml
[cvat]
host = "https://app.cvat.ai"
username = "your-username"
password = "your-password"
```

### Приоритет настроек

Настройки загружаются из нескольких источников (в порядке приоритета):

1. **CLI-аргументы** (`--host`, `--token` и т.д.) — наивысший приоритет
2. **Переменные окружения** (`CVAT_HOST`, `CVAT_TOKEN` и т.д.)
3. **Файл конфигурации** (`~/.config/cveta2/config.toml`)
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

# Указать альтернативный конфиг-файл
uv run cveta2 fetch --project-id 123 --config /path/to/config.toml

# Также работает как python-модуль
uv run python -m cveta2 fetch --project-id 123
```

### Как Python-библиотека

```python
from cveta2 import fetch_annotations
from cveta2.config import CvatConfig

# Конфиг загрузится из файла + env автоматически
cfg = CvatConfig.load(cli_host="https://app.cvat.ai", cli_token="your-token")

result = fetch_annotations(cfg, project_id=123)

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

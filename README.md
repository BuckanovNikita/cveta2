# cveta2

Утилита для выгрузки аннотаций из CVAT-проектов. Доступна как CLI (`cveta2 fetch`) и как Python API (`CvatClient`, `fetch_annotations`).

## Что умеет

- Собирает **все bbox-аннотации** проекта в плоский список — одна запись на каждый bounding box
- Возвращает **список удалённых изображений** по всем задачам проекта
- **Автоматически разделяет** результат на актуальный датасет, устаревшие данные и данные в работе
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

### Приоритет источников

1. **Переменные окружения** — переопределяют файл
2. **Файл конфигурации** (`~/.config/cveta2/config.yaml`)
3. **Интерактивный ввод** — если не указаны логин/пароль/токен

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

### Неинтерактивный режим

Для использования в CI/скриптах установите `CVETA2_NO_INTERACTIVE=true`. В этом режиме:

- Все интерактивные промпты заменяются на ошибки с подсказкой, какой флаг или переменную окружения нужно использовать
- Команда `setup` недоступна — настраивайте через env-переменные или редактируя файл конфигурации напрямую
- При `fetch` без `--project` — ошибка (укажите `-p`)
- Если не хватает учётных данных — ошибка (задайте `CVAT_TOKEN` или `CVAT_USERNAME`/`CVAT_PASSWORD`)
- Если выходная директория уже существует — перезаписывается без вопросов

Переменная может быть не установлена вообще — по умолчанию интерактивный режим включён.

```bash
# Пример CI-использования
export CVAT_HOST="https://app.cvat.ai"
export CVAT_TOKEN="your-token"
export CVETA2_NO_INTERACTIVE=true

cveta2 fetch -p 123 -o output/
```

## CLI: примеры

```bash
# Первоначальная настройка
cveta2 setup

# Базовый fetch
cveta2 fetch --project 123 -o output/
cveta2 fetch -p "Имя проекта" -o output/

# Интерактивный выбор проекта (из кэша; в списке есть опция обновить с CVAT)
cveta2 fetch -o output/

# Дополнительно сохранить полный (необработанный) CSV
cveta2 fetch -p 123 -o output/ --raw

# Обрабатывать только задачи со статусом completed
cveta2 fetch -p 123 -o output/ --completed-only

# Путь к конфигу через env (кэш проектов — projects.yaml в той же папке)
CVETA2_CONFIG=/path/to/config.yaml cveta2 fetch -p 123 -o output/
```

## Python API

```python
from cveta2 import CvatClient, fetch_annotations
from cveta2.config import CvatConfig

# Конфиг загрузится из файла и env (или выполните cveta2 setup)
cfg = CvatConfig.load()

client = CvatClient(cfg)
result = client.fetch_annotations(project_id=123, completed_only=True)

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

## Ограничения

- Извлекаются только фигуры типа `rectangle` (в выходе это `instance_shape="box"`). Другие типы фигур CVAT (`polygon`, `polyline`, `points` и т.д.) пропускаются.

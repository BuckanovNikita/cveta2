# Скрипты (scripts/)

Вспомогательные скрипты для разработки и тестов. Запускать из корня репозитория: `uv run python scripts/<script>.py ...`.

## upload_dataset_to_cvat.py

Создаёт CVAT-проект и несколько задач из датасетного YAML (например coco8).

**Назначение:** быстро поднять проект в CVAT с теми же изображениями и метками, что в локальном датасете (train/val), и при необходимости загрузить bbox-аннотации из YOLO-разметки.

**Зависимости:** `cveta2.config.CvatConfig`, cvat_sdk. Учётные данные — из конфига или интерактивного ввода.

**Примеры:**

```bash
# Проект coco8-dev, 8 задач, YAML по умолчанию tests/fixtures/data/coco8.yaml
uv run python scripts/upload_dataset_to_cvat.py --project coco8-dev --tasks 8

# Свой YAML и имя проекта
uv run python scripts/upload_dataset_to_cvat.py --yaml path/to/dataset.yaml --project my-project --tasks 3
```

**Аргументы:**

| Аргумент   | Описание |
|-----------|----------|
| `--yaml`  | Путь к YAML датасета (path, train, val, names). По умолчанию `tests/fixtures/data/coco8.yaml`. |
| `--project` | Имя создаваемого проекта в CVAT. |
| `--tasks` | Количество задач (в каждой — один и тот же набор изображений train+val). |

---

## export_cvat_fixtures.py

Выгружает данные проекта CVAT в JSON-фикстуры для тестов.

**Назначение:** получить снапшот проекта (задачи, кадры, аннотации) без использования cveta2-клиента, чтобы тесты не зависели от кода библиотеки. Формат JSON совпадает с DTO из `cveta2._client.dtos` (RawTask, RawDataMeta, RawAnnotations и т.д.).

**Зависимости:** только cvat_sdk. cveta2 не импортируется. Учётные данные — только из переменных окружения.

**Примеры:**

```bash
# Выгрузить проект coco8-dev в каталог по умолчанию tests/fixtures/cvat/coco8-dev/
export CVAT_HOST="http://localhost:8080"
export CVAT_USERNAME="admin"
export CVAT_PASSWORD="your_password"
uv run python scripts/export_cvat_fixtures.py --project coco8-dev

# Другой проект и каталог
uv run python scripts/export_cvat_fixtures.py --project other-project --output-dir tests/fixtures/cvat/other-project
```

**Переменные окружения:**

| Переменная       | Описание        |
|------------------|-----------------|
| `CVAT_HOST`      | URL сервера CVAT (обязательно). |
| `CVAT_USERNAME`  | Имя пользователя (обязательно). |
| `CVAT_PASSWORD`  | Пароль (обязательно). |

**Аргументы:**

| Аргумент       | Описание |
|----------------|----------|
| `--project`    | Имя проекта в CVAT (по умолчанию `coco8-dev`). |
| `--output-dir` | Каталог для вывода (по умолчанию `tests/fixtures/cvat/coco8-dev`). |

**Результат:** в `output-dir` создаются `project.json` (id, name, labels) и `tasks/<task_id>_<slug>.json` (task, data_meta, annotations). Эти файлы читает `tests.fixtures.load_cvat_fixtures.load_cvat_fixtures()` и проверяют тесты в `tests/test_cvat_fixtures.py`.

---

## clone_project_to_s3.py

Клонирует CVAT-проект, перенося изображения задач в S3 cloud storage.

**Назначение:** создать копию проекта, в которой все изображения хранятся в S3 (а не загружены напрямую в CVAT). Используется для подготовки тестовых проектов с cloud storage backend.

**Зависимости:** `cveta2.config.CvatConfig`, cvat_sdk, boto3. CVAT-креды — из конфига (`~/.config/cveta2/config.yaml`). S3-креды — из стандартной цепочки boto3 (`~/.aws/credentials`, env-переменные и т.д.).

**Примеры:**

```bash
# Клонировать coco8-dev → coco8-dev-s3, используя cloud storage #1
uv run python scripts/clone_project_to_s3.py --source coco8-dev --dest coco8-dev-s3 --cloud-storage-id 1
```

**Аргументы:**

| Аргумент | Описание |
|----------|----------|
| `--source` | Имя исходного проекта в CVAT (обязательно). |
| `--dest` | Имя нового проекта (обязательно). |
| `--cloud-storage-id` | ID cloud storage в CVAT, куда загружать изображения (обязательно). |

**Что делает:**

1. Скачивает кадры из первой задачи исходного проекта через CVAT API.
2. Загружает их в S3-бакет, указанный в cloud storage (`prefix/dest_name/filename`).
3. Создаёт новый проект с теми же метками.
4. Для каждой задачи создаёт новую задачу с cloud storage data source, копирует аннотации и удалённые кадры.

# cveta2

Командная утилита и Python-библиотека для работы с разметкой в CVAT. cveta2 выгружает
bbox-аннотации проекта в CSV, скачивает изображения из S3, создаёт задачи (tasks) в CVAT из
готового CSV, конвертирует разметку в YOLO и COCO, проверяет датасет и публикует его в ClearML.

Документация: [docs/README.md](docs/README.md).

## Установка

Нужен Python 3.12 или 3.13. Пакет ставится из git-репозитория по тегу версии:

```bash
uv add git+ssh://git@<host>/<org>/cveta2@vX.Y.Z
pip install git+ssh://git@<host>/<org>/cveta2@vX.Y.Z
```

Вместо тега можно указать хеш коммита:

```bash
uv add git+ssh://git@<host>/<org>/cveta2@<хеш-коммита>
```

Команды, которые работают с ClearML (`verify --bundle`, `upload-dataset`, `dataset`), требуют
extra `clearml`:

```bash
uv add "cveta2[clearml] @ git+ssh://git@<host>/<org>/cveta2@vX.Y.Z"
```

## Быстрый старт

```bash
cveta2 setup                               # подключение к CVAT
cveta2 setup-cache                         # куда складывать изображения
cveta2 doctor                              # проверить настройки
cveta2 fetch --project "My project" -o output/   # выгрузить разметку проекта в CSV
cveta2 convert --to-yolo -d output/dataset.csv -o yolo/   # CSV → YOLO
```

`fetch` пишет в `output/` четыре CSV-файла; их состав описан в
[формате датасета](docs/dataset-format.md). Полные сценарии — в
[docs/workflows.md](docs/workflows.md).

## Команды

| Команда | Что делает |
| --- | --- |
| [`setup`](docs/commands/setup.md) | Настроить подключение к CVAT |
| [`setup-cache`](docs/commands/setup-cache.md) | Настроить каталоги кэша изображений |
| [`doctor`](docs/commands/doctor.md) | Проверить конфигурацию и кэш |
| [`fetch`](docs/commands/fetch.md) | Выгрузить все аннотации проекта |
| [`fetch-task`](docs/commands/fetch-task.md) | Выгрузить аннотации выбранных задач |
| [`whats-new`](docs/commands/whats-new.md) | Показать задачи, завершённые после прошлой выгрузки |
| [`s3-sync`](docs/commands/s3-sync.md) | Скачать изображения из S3 в локальный кэш |
| [`upload`](docs/commands/upload.md) | Создать задачу в CVAT из `dataset.csv` |
| [`merge`](docs/commands/merge.md) | Объединить два CSV-файла датасета |
| [`convert`](docs/commands/convert.md) | Конвертировать CSV в YOLO и COCO, YOLO в CSV |
| [`labels`](docs/commands/labels.md) | Посмотреть и изменить метки (labels) проекта |
| [`ignore`](docs/commands/ignore.md) | Вести список задач, которые `fetch` пропускает |
| [`task`](docs/commands/task.md) | Изменить задачу: удалить кадры, аннотации метки, саму задачу, сменить статус |
| [`verify`](docs/commands/verify.md) | Проверить CSV или подготовить датасет к публикации |
| [`upload-dataset`](docs/commands/upload-dataset.md) | Опубликовать подготовленный датасет в ClearML |
| [`dataset`](docs/commands/dataset.md) | Управлять именованными датасетами: выгрузка, подготовка, публикация |

Флаги любой команды показывает `cveta2 <команда> --help`.

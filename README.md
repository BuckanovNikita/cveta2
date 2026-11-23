# cveta2

Командная утилита и Python-библиотека для работы с разметкой в CVAT. cveta2 выгружает
bbox-аннотации проекта в CSV, скачивает изображения из S3, создаёт задачи (tasks) в CVAT из
готового CSV, конвертирует разметку в YOLO и COCO, проверяет датасет и публикует его в ClearML.

Документация: [docs/README.md](docs/README.md). Термины: [GLOSSARY.md](GLOSSARY.md).

## Установка

Нужен Python 3.12 или 3.13 и сервер CVAT 2.82.0 или новее. Пакет ставится из git-репозитория по тегу версии:

```bash
uv add git+ssh://git@<host>/<org>/cveta2@vX.Y.Z
pip install git+ssh://git@<host>/<org>/cveta2@vX.Y.Z
```

Вместо тега можно указать хеш коммита:

```bash
uv add git+ssh://git@<host>/<org>/cveta2@<хеш-коммита>
```

ClearML SDK ставится вместе с пакетом, а его подключение к серверу ClearML настраивается отдельно. Оно нужно для `verify --bundle`, `upload-dataset` и команд `cveta2 dataset`, которые читают или публикуют версии в ClearML. Настройте его файлом `~/clearml.conf` (или файлом из `CLEARML_CONFIG_FILE`) либо переменными `CLEARML_API_HOST`, `CLEARML_API_ACCESS_KEY` и `CLEARML_API_SECRET_KEY`; если адрес сервера API не вида `api.<домен>` и без порта 8008, задайте ещё `CLEARML_WEB_HOST` и `CLEARML_FILES_HOST`. Проверить настройку можно командой [`cveta2 doctor`](docs/commands/doctor.md).

## Быстрый старт

```bash
cveta2 setup --global-config ~/team/project-config.yaml   # подключить общую конфигурацию команды
cveta2 setup                                               # логин и пароль CVAT (в терминале)
cveta2 setup-cache                                         # куда складывать изображения (в терминале)
cveta2 doctor                                              # проверить настройки
cveta2 fetch -p "Retail shelves" -o output/                # выгрузить разметку в CSV, изображения — в кэш
```

`fetch` пишет в `output/` четыре CSV-файла; их состав описан в
[формате данных](docs/dataset-format.md). Перед конвертацией в YOLO или COCO назначьте split:
`fetch` оставляет его пустым. Как это сделать и что дальше — в [сценариях работы](docs/workflows.md).

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
| [`task`](docs/commands/task.md) | Изменить задачу: пометить кадры удалёнными, удалить аннотации метки или задачу, сменить stage и state |
| [`verify`](docs/commands/verify.md) | Проверить CSV или подготовить датасет к публикации |
| [`upload-dataset`](docs/commands/upload-dataset.md) | Опубликовать подготовленный датасет в ClearML |
| [`dataset`](docs/commands/dataset.md) | Управлять именованными датасетами: выгрузка, подготовка, публикация |

Флаги любой команды показывает `cveta2 <команда> --help`.

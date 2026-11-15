# cveta2

Командная утилита и Python-библиотека для работы с разметкой в CVAT. Выгружает
bbox-аннотации проекта в CSV, скачивает изображения из S3, создаёт задачи из готового
датасета, конвертирует разметку в YOLO и COCO, проверяет датасет и публикует его
в ClearML.

## Установка

Нужен Python 3.12 или 3.13. Пакет ставится из git-репозитория по тегу версии:

```bash
uv add git+ssh://git@<host>/<org>/cveta2@vX.Y.Z
pip install git+ssh://git@<host>/<org>/cveta2@vX.Y.Z
```

Или из собранного файла:

```bash
pip install cveta2-<версия>-py3-none-any.whl
```

Сабмодулей у репозитория нет, поэтому подойдёт любое зеркало или внутренний git-хост.
Зависимости берутся с PyPI или внутреннего индекса. Для публикации в ClearML нужен
extra `clearml`; всё остальное работает без него.

## Быстрый старт

Подключитесь к CVAT и укажите, куда складывать изображения:

```bash
cveta2 setup
cveta2 setup-cache
```

Выгрузите проект — по ID, по имени или выбрав его из списка:

```bash
cveta2 fetch --project 123 -o output/
cveta2 fetch --project "Мой проект" -o output/
cveta2 fetch -o output/
```

В `output/` появятся четыре файла:

| Файл | Что в нём |
| --- | --- |
| `dataset.csv` | актуальная разметка |
| `obsolete.csv` | устаревшая разметка |
| `in_progress.csv` | разметка из задач, которые ещё в работе |
| `deleted.csv` | удалённые изображения |

Одна строка CSV — один bounding box. Точный состав столбцов описан в
[контракте датасета](docs/dataset-contract.md) (на английском).

Отдельные задачи выгружаются командой `fetch-task`:

```bash
cveta2 fetch-task -p 123 -t 456 789 -o output/
cveta2 fetch-task -p 123 -t "Партия 3" -o output/
cveta2 fetch-task -p 123 -o output/    # выбрать задачи из списка
```

Если чего-то не хватает, команда спросит это в терминале, а в конце напечатает
полный вариант с флагами, чтобы следующий запуск повторить без вопросов. Для скриптов
и CI есть [неинтерактивный режим](docs/configuration.md#неинтерактивный-режим).

## Команды

| Команда | Что делает |
| --- | --- |
| [`setup`](docs/cli.md#настроить-подключение-к-cvat-cveta2-setup) | Настроить подключение к CVAT |
| [`setup-cache`](docs/cli.md#настроить-кэш-изображений-cveta2-setup-cache) | Настроить пути кэша изображений |
| [`doctor`](docs/cli.md#проверить-конфигурацию-cveta2-doctor) | Проверить конфигурацию и права на кэш |
| [`fetch`](docs/cli.md#выгрузить-все-аннотации-проекта-cveta2-fetch) | Выгрузить все аннотации проекта |
| [`fetch-task`](docs/cli.md#выгрузить-конкретные-задачи-cveta2-fetch-task) | Выгрузить выбранные задачи |
| [`whats-new`](docs/cli.md#что-нового-в-проекте-cveta2-whats-new) | Показать задачи, завершённые после прошлой выгрузки |
| [`s3-sync`](docs/cli.md#синхронизировать-изображения-из-s3-cveta2-s3-sync) | Скачать изображения из S3 в локальный кэш |
| [`upload`](docs/cli.md#создать-задачу-и-загрузить-аннотации-cveta2-upload) | Создать задачу в CVAT из `dataset.csv` и перенести в неё аннотации |
| [`merge`](docs/cli.md#объединить-два-датасета-cveta2-merge) | Объединить два `dataset.csv` |
| [`convert`](docs/cli.md#конвертировать-между-форматами-cveta2-convert) | Конвертировать CSV в YOLO и обратно, CSV в COCO |
| [`labels`](docs/cli.md#управлять-метками-проекта-cveta2-labels) | Посмотреть и изменить метки проекта |
| [`ignore`](docs/cli.md#управлять-игнорируемыми-задачами-cveta2-ignore) | Вести список задач, которые `fetch` пропускает |
| [`task`](docs/cli.md#операции-над-задачами-cveta2-task) | Пометить кадры удалёнными, убрать аннотации метки, удалить задачу, сменить статус |
| [`verify`](docs/cli.md#проверить-csv-и-подготовить-пакет-cveta2-verify) | Проверить CSV или подготовить датасет к публикации |
| [`upload-dataset`](docs/cli.md#опубликовать-подготовленный-пакет-cveta2-upload-dataset) | Опубликовать подготовленный датасет в ClearML |
| [`dataset`](docs/cli.md#управляемый-датасет-cveta2-dataset) | Собрать датасет из нескольких источников, подготовить и опубликовать |

Флаги и примеры для каждой команды — в [docs/cli.md](docs/cli.md).

Что полезно знать заранее:

- Проект можно задать как ID, имя или `организация/имя`. Если имя подходит нескольким
  проектам, команда остановится и перечислит их ID.
- Выгружаются только прямоугольники. Полигон заменяется охватывающим его
  прямоугольником, остальные фигуры и треки пропускаются; обо всём этом команда
  предупреждает. [Подробнее](docs/cli.md#фигуры-при-выгрузке).
- Аннотации завершённых задач кэшируются локально и в S3-бакете проекта, поэтому
  повторный `fetch` не скачивает их заново. [Как устроен кэш](docs/images-and-cache.md#кэш-аннотаций-задач).
- `fetch --completed-only` берёт только завершённые задачи, `--no-images` не скачивает
  изображения, `--raw` дополнительно сохраняет необработанный `raw.csv`.

## Публикация датасета в ClearML

`fetch` ничего не публикует. Публикация состоит из трёх шагов, и между вторым и третьим
вы сами смотрите на результат.

1. Назначьте каждой строке выборку `train`, `val` или `test`. Этого cveta2 не делает.
2. Подготовьте пакет: команда проверит разметку и изображения и сложит результат
   вместе с отчётами в новую директорию.
3. Просмотрите отчёты и опубликуйте пакет.

```bash
cveta2 verify output --bundle --output-dir prepared \
  --project CV/datasets --dataset-name reviewed \
  --api-url https://classes.example.org/api/classes \
  --local-root /data/images --s3-root s3://images/project \
  --accept-default-classes --accept-class-changes --non-interactive

cveta2 upload-dataset prepared
```

В ClearML попадают только `dataset.csv`, `dataset.yaml` и `tasks.yaml`; изображения
остаются там, где лежат. Если после подготовки что-то изменилось — файлы, изображения,
классы, — `upload-dataset` откажется публиковать, и пакет нужно подготовить заново.

`verify` годится и для обычной проверки одного CSV, без публикации:

```bash
cveta2 verify output/dataset.csv --profile cveta2 --output-dir inspection
```

По умолчанию это только отчёт. Исправленную копию команда пишет лишь с `--clean`,
исходный файл не меняется никогда. Все флаги и коды выхода —
в [описании `verify`](docs/cli.md#проверить-csv-и-подготовить-пакет-cveta2-verify).

### Датасет из нескольких источников

Когда один датасет собирается из нескольких проектов CVAT и готовых CSV в S3,
состав источников описывают один раз в общем файле, а дальше работают с датасетом
по имени:

```bash
cveta2 setup --project-config /shared/cveta2/project-config.yaml
cveta2 dataset fetch construction --output-dir fetched
# ваш скрипт читает fetched и пишет transformed.csv
cveta2 dataset prepare construction transformed.csv \
  --source fetched --output-dir prepared --clean
cveta2 dataset report-errors prepared
cveta2 dataset publish prepared
```

`prepare` сама делит изображения на `train`/`val`/`test` в пропорции 60/20/20 и
сохраняет прежнее распределение при следующих сборках. `report-errors` заводит issues
в CVAT для ошибок, которые удаётся привязать к конкретному кадру, `publish` публикует
датасет в ClearML. Без `--clean` `prepare` только составляет отчёт, с которого и стоит
начать.
[Полный сценарий](docs/cli.md#управляемый-датасет-cveta2-dataset).

## Python API

У каждой команды, работающей с данными, есть одноимённая функция:

```python
import cveta2

result = cveta2.fetch("my-project", output_dir="out")
print(result.dataset)
```

Остальное — в [docs/python-api.md](docs/python-api.md).

## Настройка

Настроек два файла. Личный `~/.config/cveta2/config.yaml` хранит учётные данные,
локальные пути, таймауты и число потоков. Общий файл команды описывает сервер и
организацию CVAT, проекты, источники и правила сборки датасетов; путь к нему задаётся
через `cveta2 setup --project-config PATH` или переменную `CVETA2_PROJECT_CONFIG`.
Старый конфиг, где всё было в одном файле, разделяет `cveta2 setup --migrate-config`.

`cveta2 doctor` проверяет конфигурацию, доступ к S3 и права на каталоги кэша.

Формат файлов, переменные окружения, повторы запросов и параллельность описаны
в [docs/configuration.md](docs/configuration.md).

## Документация

- [docs/cli.md](docs/cli.md) — все команды и флаги.
- [docs/configuration.md](docs/configuration.md) — конфигурация и переменные окружения.
- [docs/images-and-cache.md](docs/images-and-cache.md) — изображения из S3, кэш, публикация.
- [docs/python-api.md](docs/python-api.md) — Python API.
- [docs/dataset-contract.md](docs/dataset-contract.md) — формат CSV (на английском).
- [CHANGELOG.md](CHANGELOG.md) — что менялось между версиями.

## Разработка

```bash
unset UV_PROJECT_ENVIRONMENT              # использовать .venv этого рабочего дерева
uv sync --locked
bash scripts/install-hooks.sh
uv run --locked task --exit-code fix      # автоисправления и форматирование
uv run --locked task --exit-code verify   # проверки кода, тесты, сборка
```

Хук перед коммитом запускает `verify` и не пропускает коммит, пока в рабочем дереве
есть изменения или новые файлы вне индекса.

Перед слиянием на чистом коммите запускается `uv run --locked task --exit-code acceptance`.
Он включает живые тесты, которые сами поднимают CVAT, MinIO и ClearML в отдельном
пространстве имён кластера `docker-desktop` и удаляют его по окончании; нужен `kubectl`
с этим контекстом.

Порядок работы над изменениями, правила проверки и выпуска —
в [инженерном руководстве](.specify/memory/engineering.md) (на английском).

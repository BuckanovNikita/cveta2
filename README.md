# cveta2

Утилита для работы с аннотациями CVAT-проектов: выгрузка проекта (`cveta2 fetch`), выгрузка отдельных задач (`cveta2 fetch-task`), создание задач с переносом аннотаций (`cveta2 upload`), синхронизация изображений (`cveta2 s3-sync`), управление игнорируемыми задачами (`cveta2 ignore`), управление метками проекта (`cveta2 labels`), слияние датасетов (`cveta2 merge`), конвертация между CSV и YOLO форматом (`cveta2 convert`). Доступна как CLI и как Python API (`CvatClient`, `fetch_annotations`).

## Что умеет

- Собирает **все bbox-аннотации** проекта в плоский список — одна запись на каждый bounding box
- Возвращает **список удалённых изображений** по всем задачам проекта
- **Автоматически разделяет** результат на актуальный датасет, устаревшие данные и данные в работе
- **Скачивает изображения** из S3 cloud storage, подключённого к CVAT (boto3, с кэшированием)
- **Создаёт задачи в CVAT** из `dataset.csv` — загружает изображения на S3, создаёт задачу с cloud storage и автоматически переносит bbox-аннотации
- **Выгрузка отдельных задач** (`fetch-task`) — по ID, имени или через интерактивный выбор из списка (одну или несколько)
- **Игнорирование задач** (`ignore`) — управление списком задач, которые всегда пропускаются при `fetch` (добавление/удаление по ID или имени, интерактивный выбор, просмотр всех проектов)
- **Управление метками** (`labels`) — просмотр и интерактивное редактирование меток проекта (добавление, переименование, изменение цвета, удаление); перед удалением проверяет количество аннотаций и требует подтверждения
- **Слияние датасетов** (`merge`) — объединение двух `dataset.csv` с учётом удалённых изображений и разрешением конфликтов (по порядку или по дате)
- **Конвертация форматов** (`convert`) — двунаправленная конвертация между cveta2 CSV и YOLO detection форматом (поддержка датасетов и предсказаний с confidence, русских меток, изображений без аннотаций)
- Поддерживает фильтр по задачам со статусом `completed`
- Всё за один вызов — без промежуточных XML/ZIP файлов

## Установка

```bash
pip install cveta2-0.1.0-py3-none-any.whl
```

## Быстрый старт

1. Настройте подключение к CVAT:

```bash
cveta2 setup
```

2. Настройте пути кэша изображений для проектов:

```bash
cveta2 setup-cache
```

3. Выгрузите проект (все задачи):

```bash
# По ID проекта
cveta2 fetch --project 123 -o output/

# По имени проекта
cveta2 fetch --project "Мой проект" -o output/

# Интерактивный выбор проекта из списка
cveta2 fetch -o output/
```

4. Или выгрузите конкретные задачи:

```bash
# По ID или имени задачи (можно несколько)
cveta2 fetch-task -p 123 -t 456 -o output/
cveta2 fetch-task -p 123 -t 456 -t 789 -o output/
cveta2 fetch-task -p 123 -t "Партия 3" -o output/

# Интерактивный выбор задач из списка (checkbox)
cveta2 fetch-task -p 123 -t -o output/
cveta2 fetch-task -p 123 -o output/
```

В папке `output/` появятся файлы: `dataset.csv`, `obsolete.csv`, `in_progress.csv`, `deleted.csv` (и `raw.csv` с `--raw`). Подробнее — в [DATASET_FORMAT.md](DATASET_FORMAT.md).

## Команды CLI

### `cveta2 setup`

Интерактивный мастер настройки подключения к CVAT: хост, организация, авторизация (токен или логин/пароль). Результат сохраняется в `~/.config/cveta2/config.yaml`.

```bash
cveta2 setup

# Указать другой путь к конфигу
cveta2 setup --config /path/to/config.yaml
```

### `cveta2 setup-cache`

Интерактивная настройка путей кэширования изображений для всех известных проектов. Сначала запрашивается **корневая директория кэша**; для каждого проекта по умолчанию предлагается путь «корень/имя_проекта». Нажмите Enter, чтобы принять значение по умолчанию или пропустить проект.

Если локальный кэш проектов пуст — автоматически загружает список с CVAT.

- **`--reset`** — переспросить путь для каждого проекта, используя только «корень/имя_проекта» как значение по умолчанию (игнорировать уже заданные пути).
- **`--list`** — вывести текущие пути кэша из конфига и выйти (без запросов и без CVAT).

```bash
cveta2 setup-cache

# Указать другой путь к конфигу
cveta2 setup-cache --config /path/to/config.yaml

# Показать текущие пути кэша
cveta2 setup-cache --list
```

### `cveta2 fetch`

Выгрузка **всех** bbox-аннотаций и удалённых изображений из проекта CVAT. Каждая задача выгружается последовательно и сохраняется как промежуточный CSV в `output/.tasks/task_{id}.csv`, после чего результаты объединяются и разбиваются на три CSV-файла + список удалённых. Если папка `--output-dir` уже существует, в интерактивном режиме будет предложено перезаписать, указать другой путь или отменить.

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

# Сохранить промежуточные CSV задач (по умолчанию удаляются после объединения)
cveta2 fetch -p 123 -o output/ --save-tasks
```

### `cveta2 fetch-task`

Выгрузка bbox-аннотаций для **конкретных задач** проекта. Использует ту же логику поштучной выгрузки задач, что и `fetch` (промежуточные CSV в `output/.tasks/`). В отличие от `fetch`, не разбивает результат на dataset/obsolete/in_progress — записывает единый `dataset.csv` и `deleted.csv` в указанную директорию. Задачи указываются по ID или имени через `-t`, либо выбираются интерактивно (checkbox с поиском).

```bash
# Одна задача по ID
cveta2 fetch-task -p 123 -t 456 -o output/

# Несколько задач
cveta2 fetch-task -p 123 -t 456 -t 789 -o output/

# По имени задачи (регистр не важен)
cveta2 fetch-task -p 123 -t "Партия 3" -t "Партия 4" -o output/

# Интерактивный выбор задач из списка (checkbox с мульти-выбором и поиском)
cveta2 fetch-task -p 123 -t -o output/

# Без -t — тоже интерактивный выбор
cveta2 fetch-task -p 123 -o output/

# Фильтры и изображения работают так же, как в fetch
cveta2 fetch-task -p 123 -t 456 -o output/ --completed-only --no-images

# Сохранить промежуточные CSV задач
cveta2 fetch-task -p 123 -t 456 -o output/ --save-tasks
```

В директории `output/` появятся `dataset.csv` и `deleted.csv`. Подробнее — в [DATASET_FORMAT.md](DATASET_FORMAT.md).

### `cveta2 s3-sync`

Синхронизация изображений из S3 cloud storage в локальный кэш для всех настроенных в `image_cache` проектов. Скачивает только отсутствующие файлы — никогда не загружает и не удаляет ничего на S3.

```bash
# Синхронизировать все настроенные проекты
cveta2 s3-sync

# Только один конкретный проект
cveta2 s3-sync -p coco8-dev
```

### `cveta2 ignore`

Управление списком игнорируемых задач для проекта. Игнорируемые задачи всегда пропускаются при `fetch` (считаются «в работе»). Задачи можно добавлять/удалять по ID или по имени. Без `--add`/`--remove`/`--list` открывается интерактивное меню.

```bash
# Добавить задачу в ignore-список (по ID)
cveta2 ignore -p "Мой проект" --add 456

# Добавить несколько задач (по ID или имени) с описанием причины
cveta2 ignore -p "Мой проект" --add 456 "Партия 3" -d "Дубликаты"

# Удалить задачу из ignore-списка
cveta2 ignore -p "Мой проект" --remove 456

# Показать игнорируемые задачи по всем проектам (не требует подключения к CVAT)
cveta2 ignore --list

# Интерактивный режим (TUI с добавлением/удалением через checkbox)
cveta2 ignore -p "Мой проект"
```

Конфигурация хранится в `config.yaml`:

```yaml
ignore:
  my-project:
    - id: 456
      name: "Партия 3"
      description: "Дубликаты"
    - id: 789
      name: "Партия 5"
```

### `cveta2 labels`

Просмотр и интерактивное редактирование меток (labels) проекта CVAT. Поддерживает добавление, переименование, изменение цвета и удаление меток. Перед удалением подсчитывает количество аннотаций, использующих метку, и требует явного подтверждения.

```bash
# Показать метки проекта
cveta2 labels -p "Мой проект" --list

# По ID проекта
cveta2 labels -p 123 --list

# Интерактивное редактирование (добавление/переименование/цвет/удаление)
cveta2 labels -p "Мой проект"

# Интерактивный выбор проекта (без -p)
cveta2 labels
```

Операции:
- **Добавление** — создаёт новую метку (цвет назначается CVAT автоматически)
- **Переименование** — безопасно: все аннотации сохраняются (меняется только имя, привязка по ID)
- **Изменение цвета** — безопасно: меняет цвет метки в формате `#rrggbb` (например, `#ff0000`). Не влияет на аннотации
- **Удаление** — **необратимо уничтожает** все аннотации (shapes), использующие метку. Перед удалением команда подсчитывает аннотации по всем задачам проекта и показывает количество. Если аннотации есть — требуется ввести имена меток для подтверждения

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

# Создать задачу и сразу отметить как completed
cveta2 upload -p "Мой проект" -d output/dataset.csv --complete

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

### `cveta2 merge`

Слияние двух CSV-файлов с аннотациями. Полезно, когда нужно объединить старый `dataset.csv` с новой выгрузкой — например, после переразметки части изображений. Оба файла должны содержать стандартные столбцы датасета (`image_name`, `instance_shape`, `instance_label`, bbox-поля); при использовании `--by-time` дополнительно нужен столбец `task_updated_date`.

```bash
# Базовое слияние — для общих изображений побеждает new
cveta2 merge --old old/dataset.csv --new new/dataset.csv -o merged.csv

# С учётом удалённых изображений
cveta2 merge --old old/dataset.csv --new new/dataset.csv --deleted new/deleted.csv -o merged.csv

# Разрешение конфликтов по дате обновления задачи (побеждает более свежая)
cveta2 merge --old old/dataset.csv --new new/dataset.csv --by-time -o merged.csv
```

Логика слияния:
- Изображения, присутствующие только в `--old` или только в `--new`, попадают в результат целиком
- Для изображений, присутствующих в обоих файлах — по умолчанию побеждает `--new`; с `--by-time` побеждает тот, у которого более свежая `task_updated_date` (при равных датах или непарсимых значениях побеждает `--new`)
- Изображения из `--deleted` исключаются из результата
- **Пропагация split:** если у изображения в `--old` был задан `split` (`train`/`val`/`test`), а у победившей стороны split пуст — значение из `--old` автоматически переносится в результат

### `cveta2 convert`

Двунаправленная конвертация между cveta2 CSV и YOLO detection форматом. Поддерживает два режима: CSV → YOLO (`--to-yolo`) и YOLO → CSV (`--from-yolo`).

**CSV → YOLO** (`--to-yolo`):

```bash
# Конвертировать dataset.csv в YOLO формат (изображения копируются через reflink/copy)
cveta2 convert --to-yolo -d dataset.csv -o yolo_dataset/

# Использовать символические ссылки вместо копирования
cveta2 convert --to-yolo -d dataset.csv -o yolo_dataset/ --link-mode symlink

# Указать дополнительную директорию с изображениями
cveta2 convert --to-yolo -d dataset.csv -o yolo_dataset/ --image-dir /mnt/data/images

# Доступные режимы --link-mode: auto (по умолчанию), reflink, hardlink, symlink, copy
```

Создаёт структуру директорий для ultralytics:

```
yolo_dataset/
  images/{train,val,test}/   -- изображения
  labels/{train,val,test}/   -- .txt файлы с аннотациями (class_id xc yc w h)
  dataset.yaml               -- конфиг датасета
```

Каждое изображение должно иметь заполненное поле `split` (`train`/`val`/`test`). Изображения без аннотаций (`instance_shape="none"`) создают пустые `.txt` файлы. Русские названия меток сохраняются в `dataset.yaml` в нечитаемом виде.

**YOLO → CSV** (`--from-yolo`):

```bash
# Конвертировать YOLO датасет (с dataset.yaml) в CSV
cveta2 convert --from-yolo -i yolo_dataset/ -o output.csv

# Конвертировать предсказания (без dataset.yaml) с файлом имён классов
cveta2 convert --from-yolo -i predictions/ -o preds.csv --names-file classes.yaml --image-dir /mnt/data/images
```

Автоматически определяет режим:
- **Режим датасета** — если в директории есть `dataset.yaml`, читает классы и сплиты из него
- **Режим предсказаний** — если `dataset.yaml` нет, обрабатывает `.txt` файлы как предсказания; для имён классов используйте `--names-file`

В режиме предсказаний поддерживается 6-е поле confidence в YOLO `.txt` файлах (формат: `class_id xc yc w h confidence`). Значение записывается в столбец `confidence` выходного CSV.

Изображения автоматически ищутся во всех директориях из `image_cache` конфига. Дополнительные пути можно указать через `--image-dir` (можно повторять).

### `cveta2 doctor`

Диагностика конфигурации и окружения. Проверяет:

- Наличие и корректность файла конфигурации (хост, креды)
- Доступность AWS/S3-учётных данных (boto3)
- Права доступа кэша изображений: у файлов проверяется групповое чтение, у директорий — групповое чтение и выполнение (чтобы все пользователи группы имели доступ)

```bash
cveta2 doctor
```

## Загрузка изображений из S3

При `fetch` cveta2 автоматически скачивает изображения проекта из S3 cloud storage, подключённого к CVAT. Используется **облачное хранилище проекта** (поле `source_storage` у самого проекта в API CVAT), а не хранилище отдельных задач. Все изображения ищутся в префиксе проекта по имени файла.

### Где хранятся изображения

Для каждого проекта вы задаёте директорию вручную — через `cveta2 setup-cache` (настройка для всех проектов сразу) или при первом `fetch`. Пути хранятся в конфиге:

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

По умолчанию используется `~/.config/cveta2/config.yaml`. Создать его проще всего через `cveta2 setup` (креды) и `cveta2 setup-cache` (пути к изображениям).

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

ignore:
  coco8-dev:
    - id: 456
      name: "Партия 3"
      description: "Дубликаты"
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
| `CVETA2_RAISE_ON_FAILURE` | При `true` — при первой ошибке CVAT 5xx по задаче вызов `fetch`/`fetch-task` сразу падает (исключение пробрасывается). По умолчанию такие задачи пропускаются, ошибка и ссылка на задачу пишутся в лог |

### Ошибки сервера CVAT (5xx)

При выгрузке аннотаций (`fetch`, `fetch-task`) возможны временные ошибки сервера (HTTP 5xx) по отдельным задачам. По умолчанию такая задача **пропускается**: в лог пишется ошибка и ссылка на задачу, остальные задачи обрабатываются дальше. В лог также выводится готовая команда для добавления сломанной задачи в список игнорируемых — при следующем запуске она не будет запрашиваться:

```text
Чтобы пропустить задачу при следующем запуске: cveta2 ignore --project "имя_проекта" --add 123
```

Если нужно, чтобы вызов завершался при первой же 5xx (например, в CI), установите `CVETA2_RAISE_ON_FAILURE=true`.

### Неинтерактивный режим

Для использования в CI/скриптах установите `CVETA2_NO_INTERACTIVE=true`. В этом режиме:

- Все интерактивные промпты заменяются на ошибки с подсказкой, какой флаг или переменную окружения нужно использовать
- Команды `setup` и `setup-cache` недоступны — настраивайте через env-переменные или редактируя файл конфигурации напрямую
- При `fetch` / `fetch-task` без `--project` — ошибка (укажите `-p`)
- При `fetch-task` без `-t` или с `-t` без значения — ошибка (укажите `-t VALUE`)
- Если не хватает учётных данных — ошибка (задайте `CVAT_TOKEN` или `CVAT_USERNAME`/`CVAT_PASSWORD`)
- Если путь к изображениям не настроен — ошибка (укажите `--images-dir`, `--no-images` или `image_cache` в конфиге)
- Если выходная директория уже существует — перезаписывается без вопросов
- Команда `upload` недоступна — выбор классов требует интерактивного режима
- Команда `ignore` без `--add`/`--remove`/`--list` недоступна (интерактивный TUI); `--add`/`--remove`/`--list` работают

Переменная может быть не установлена вообще — по умолчанию интерактивный режим включён.

```bash
# Пример CI-использования
export CVAT_HOST="https://app.cvat.ai"
export CVAT_TOKEN="your-token"
export CVETA2_NO_INTERACTIVE=true

cveta2 fetch -p 123 -o output/ --images-dir /data/images
```

## Python API

### Выгрузка аннотаций

```python
from cveta2 import CvatClient, fetch_annotations

# Вариант 1: CvatClient — полный контроль
# Конфигурация загружается автоматически (env, config file, preset)
with CvatClient() as client:
    result = client.fetch_annotations(project_id=123, completed_only=True)

    # Только конкретные задачи — по ID или имени (список)
    result = client.fetch_annotations(project_id=123, task_selector=[456])
    result = client.fetch_annotations(project_id=123, task_selector=[456, "Партия 3"])

    # result.annotations — список BBoxAnnotation и ImageWithoutAnnotations
    for ann in result.annotations[:3]:
        print(
            f"{ann.image_name}: {ann.instance_label} "
            f"[{ann.bbox_x_tl}, {ann.bbox_y_tl}, {ann.bbox_x_br}, {ann.bbox_y_br}]"
        )

    # result.deleted_images — список DeletedImage
    for img in result.deleted_images:
        print(f"Удалено: {img.image_name} (task={img.task_id})")

# Вариант 1б: явная конфигурация (если нужны нестандартные настройки)
from cveta2 import CvatConfig

cfg = CvatConfig.load()
with CvatClient(cfg) as client:
    result = client.fetch_annotations(project_id=123)

# Вариант 2: функция-обёртка — сразу DataFrame
df = fetch_annotations(project_id=123)
print(df.head())
```

### Работа с проектами

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

### Управление метками

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

### Создание задачи и загрузка аннотаций

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

### Загрузка и синхронизация изображений

```python
from pathlib import Path
from cveta2 import CvatClient

with CvatClient() as client:
    project_id = client.resolve_project_id("Мой проект")

    # Скачать изображения по результатам fetch
    result = client.fetch_annotations(project_id=project_id)
    stats = client.download_images(result, Path("/mnt/data/my-project"))
    print(f"Загружено: {stats.downloaded}, из кэша: {stats.cached}, ошибок: {stats.failed}")

    # Синхронизировать все изображения из S3 (без привязки к аннотациям)
    cs_info = client.detect_project_cloud_storage(project_id)
    stats = client.sync_project_images(
        project_id=project_id,
        target_dir=Path("/mnt/data/my-project"),
        project_cloud_storage=cs_info,
    )
    print(f"Синхронизировано: {stats.downloaded} новых, {stats.cached} уже было")
```

## Формат данных

Подробное описание формата выходных CSV и моделей данных — в [DATASET_FORMAT.md](DATASET_FORMAT.md).

## Ограничения

- Извлекаются только фигуры типа `rectangle` (в выходе это `instance_shape="box"`). Другие типы фигур CVAT (`polygon`, `polyline`, `points` и т.д.) пропускаются.

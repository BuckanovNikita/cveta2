# Конфигурация

cveta2 читает настройки из двух YAML-файлов и из переменных окружения. Эта страница описывает оба файла, все ключи, все переменные окружения и неинтерактивный режим.

## Два файла

| Файл | Для чего | Кто его ведёт |
|---|---|---|
| Личная конфигурация ([personal configuration](../GLOSSARY.md)) | Логин и пароль CVAT, локальные пути кэша, настройки сети и `upload`, ссылка на общий файл. | Вы сами, обычно через [`cveta2 setup`](commands/setup.md). |
| Общая конфигурация ([global configuration](../GLOSSARY.md)) | Сервер CVAT и организация, описания проектов ([project definition](../GLOSSARY.md)), управляемые датасеты ([managed dataset](../GLOSSARY.md)). Паролей и локальных путей в нём нет. | Команда. Вы получаете готовый файл. |

Файлы не сливаются. Единственное исключение — настройки публикации: личный файл может заменить их, если общий файл это разрешает, см. [локальные переопределения](#локальные-переопределения).

### Где cveta2 ищет личную конфигурацию

Порядок, первое найденное значение побеждает:

1. Флаг `--config PATH` (есть у `setup` и команд `dataset`).
2. Переменная окружения `CVETA2_CONFIG`.
3. `~/.config/cveta2/config.yaml`.

Если файла нет, cveta2 работает со значениями по умолчанию и переменными окружения.

Рядом с личным файлом, в том же каталоге, cveta2 хранит `projects.yaml`: кэш списка проектов CVAT по организациям. Его заполняют команды, которые запрашивают список проектов; вручную его вести не нужно.

### Где cveta2 ищет общую конфигурацию

cveta2 выбирает ровно один общий файл. Уровни проверяются по порядку, первый заданный побеждает:

1. Флаг `--global-config PATH` (команды `dataset`; у `setup` этот флаг подключает файл, см. ниже).
2. Переменная окружения `CVETA2_GLOBAL_CONFIG`.
3. Ключ `global_config` в личном файле. Относительный путь считается от каталога личного файла.

Если не найдено ничего, общий файл не используется. Если путь выбран, а файла нет, команда завершается ошибкой `Cannot read configuration <путь>: FileNotFoundError`.

Старые написания `--project-config`, `CVETA2_PROJECT_CONFIG` и `project_config` больше не поддерживаются. Флаг `--project-config` — неизвестный аргумент (код `2`), переменная `CVETA2_PROJECT_CONFIG` ничего не выбирает, а личный файл со `schema_version: 1` и ключом `project_config` отклоняется: `Personal configuration contains unsupported/shared sections: project_config`. Переименуйте ключ в `global_config`.

### Как подключить общий файл

```bash
cveta2 setup --global-config ~/team/project-config.yaml
```

Команда проверяет общий файл и записывает в личный файл `schema_version: 1` и абсолютный путь в `global_config` Сам общий файл она не меняет. Подробности — в [`cveta2 setup`](commands/setup.md).

Если общего файла ещё нет, его создаёт `--global` с адресом CVAT. Новый файл разрешает локальные переопределения (`local_overrides: true`) и сразу подключается:

```bash
cveta2 setup --global --global-config ~/team/project-config.yaml --host https://cvat.example.com --organization my-team
```

Ключи общего файла записываются командой `cveta2 setup --global` по одному флагу на ключ, без ручной правки YAML:

| Ключ | Команда |
|---|---|
| `local_overrides` | `cveta2 setup --global --local-overrides on` (или `off`) |
| `cvat.host`, `cvat.organization` | `cveta2 setup --global --host URL --organization SLUG` |
| `projects.<ключ>.sync_root`, `.ignored_prefix`, `.task_cache_s3` | `cveta2 setup --global --project P --sync-root s3://bucket/prefix --ignored-prefix PREFIX --task-cache-s3 s3://bucket/cache` |
| `projects.<ключ>.publication.clearml.project`, `.clearml.dataset`, `.clearml.output_uri` | `cveta2 setup --global --project P --clearml-project Retail/Datasets --dataset-name retail-shelves --output-uri s3://bucket/.clearml` |
| `projects.<ключ>.publication.api_url` | `cveta2 setup --global --project P --api-url https://classes.example.com/api` |
| `projects.<ключ>.publication.empty_classes`, `.s3_roots` | `cveta2 setup --global --project P --empty-class 12 --empty-class 13 --s3-root s3://bucket/images` |

`--unset <флаг без -->` удаляет ключ, `--unset publication` — весь блок публикации. Проект без описания получает его при первой записи: ID и имя берутся из `projects.yaml` или из CVAT.

## Личная конфигурация

### Пример

```yaml
schema_version: 1                      # формат личного файла с подключённым общим файлом
global_config: /home/alice/team/project-config.yaml

cvat:
  username: alice
  password: "ваш-пароль"
  request_timeout: 60                  # секунды; необязательно

cache:
  images_root: /home/alice/data/images           # общий корень кэша изображений
  tasks_root: /home/alice/data/task_annotations  # локальный кэш аннотаций
  projects:
    Retail shelves:
      images_root: /home/alice/data/retail       # свой корень для одного проекта

image_cache:
  Retail shelves: /home/alice/data/retail-shelves   # явный каталог изображений проекта

network:
  s3_workers: 16
  cvat_workers: 4
  retry_attempts: 5
  retry_max_wait: 30

upload:
  images_per_job: 100
  image_quality: 100
```

Файл содержит пароль. cveta2 записывает его с правами `0600`. Если при чтении у файла с паролем есть права для группы или других пользователей, cveta2 сам ограничивает их до `0600` и пишет предупреждение `Права файла с паролем <путь> ограничены до 0600.` Если файл принадлежит другому пользователю, cveta2 только предупреждает.

### Ключи личного файла

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `schema_version` | число | нет | `1` — формат с подключённым общим файлом. С `schema_version: 1` обязателен `global_config`, и в файле разрешены только ключи из этой таблицы. |
| `global_config` | путь | нет | Путь к общему файлу. Непустая строка. |
| `cvat.username` | строка | нет | Логин CVAT. |
| `cvat.password` | строка | нет | Пароль CVAT. |
| `cvat.request_timeout` | число ≥ 0 | нет | Таймаут чтения ответа в секундах для запросов к CVAT и для S3. Без значения или `0` таймаут чтения не задаётся. Таймаут соединения — 10 секунд: для S3 всегда, для CVAT только когда задан таймаут чтения. |
| `cvat.host` | строка | `http://localhost:8080` | Адрес CVAT. Только в личном файле без общего файла; с `schema_version: 1` запрещён. |
| `cvat.organization` | строка | нет | Slug организации CVAT. Пусто — личное пространство. Те же ограничения, что у `cvat.host`. |
| `cache.images_root` | путь | нет | Корень кэша изображений: проект без явного пути получает каталог `<images_root>/<имя проекта>`. |
| `cache.tasks_root` | путь | нет | Корень локального кэша аннотаций ([annotation cache](../GLOSSARY.md)). |
| `cache.projects.<проект>.images_root` | путь | `cache.images_root` | Свой корень изображений для проекта. |
| `cache.projects.<проект>.tasks_root` | путь | `cache.tasks_root` | Свой корень кэша аннотаций для проекта. |
| `image_cache.<проект>` | путь | нет | Явный каталог изображений проекта. Важнее `images_root`. |
| `network.s3_workers` | целое > 0 | `16` | Сколько объектов S3 передавать одновременно. |
| `network.cvat_workers` | целое > 0 | `4` | Сколько запросов к CVAT выполнять одновременно. |
| `network.retry_attempts` | целое ≥ 2 | `5` | Сколько всего попыток делать для сетевой операции. |
| `network.retry_max_wait` | число > 0 | `30` | Максимальная пауза между попытками в секундах. |
| `upload.images_per_job` | целое > 0 | `100` | Сколько кадров (frame) в одном job при создании задачи (task) командой `upload`. |
| `upload.image_quality` | целое 1–100 | `100` | Качество сжатия кадров, которое `upload` передаёт в CVAT. |
| `overrides.projects.<ключ>.publication` | словарь | нет | Личные значения настроек публикации проекта. Только с `schema_version: 1`; см. [локальные переопределения](#локальные-переопределения). |

Пути в разделах `cache` и `image_cache` пишите абсолютными: при чтении файла cveta2 не раскрывает `~`. Мастер [`cveta2 setup`](commands/setup.md#мастер-личной-настройки) сам записывает абсолютные пути.

Подробно о каталогах кэша — на странице [Изображения и кэши](images-and-cache.md).

Ключи `cache.projects.<проект>.ignored_prefix` и `cache.projects.<проект>.task_cache_s3` принадлежат общему файлу (см. ниже). В личном файле с `schema_version: 1` они вызывают ошибку.

## Общая конфигурация

### Пример

```yaml
schema_version: 1
local_overrides: true                   # разрешить личные переопределения; без ключа — false

cvat:
  host: https://cvat.example.com        # только http(s), без логина и пароля в адресе
  organization: my-team                 # пусто или null — личное пространство

projects:
  retail:                               # ключ: латиница, цифры, _ и -
    id: 123                             # ID проекта в CVAT
    name: Retail shelves                # имя проекта в CVAT
    sync_root: s3://my-bucket/images    # корень синхронизации для s3-sync
    ignored_prefix: images/             # отбрасываемый префикс ключей S3
    task_cache_s3: s3://my-bucket/cache # где хранить кэш аннотаций в S3
    ignore:                             # список игнорируемых задач
      - id: 456
        name: "batch 7"
        description: "переразметка"
        silent: false
    publication:                        # необязательный блок: настройки публикации
      clearml:
        project: Retail/Datasets        # обязателен в блоке
        dataset: retail-shelves         # обязателен в блоке
        output_uri: s3://my-bucket/.clearml   # необязателен
      api_url: https://classes.example.com/api   # обязателен в блоке
      empty_classes: [12]               # необязателен, по умолчанию []
      s3_roots: [s3://my-bucket/images] # необязателен

datasets:
  retail-shelves:                       # управляемый датасет, см. commands/dataset.md
    sources:
      - name: cvat-main
        type: cvat
        project: retail
    clearml:
      project: Retail/Datasets
      dataset: retail-shelves
    api_url: https://classes.example.com/api
```

### Ключи общего файла

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `schema_version` | число | `1` | Только `1`. |
| `local_overrides` | булево | `false` | Разрешает личным файлам переопределять настройки публикации (см. [локальные переопределения](#локальные-переопределения)). Ключ не записывается, пока он `false`. |
| `cvat.host` | строка | обязателен | Адрес CVAT, `http` или `https`, без логина и пароля. Завершающий `/` отбрасывается. |
| `cvat.organization` | строка | нет | Slug организации. Пусто или `null` — личное пространство. |
| `projects.<ключ>` | словарь | `{}` | Описание проекта. Ключ — латиница, цифры, `_` и `-`, начинается с буквы или цифры. |
| `projects.<ключ>.id` | целое ≥ 0 | обязателен | ID проекта в CVAT. ID не повторяются. |
| `projects.<ключ>.name` | строка | `""` | Имя проекта в CVAT. Описание применяется к проекту CVAT, имя которого совпадает с этим значением или с ключом. В аргументе `-p` команд ключ не работает: там нужен ID или имя проекта в CVAT. |
| `projects.<ключ>.sync_root` | строка | нет | Корень синхронизации ([sync root](../GLOSSARY.md)): `s3://bucket/prefix` или непустой префикс в бакете проекта. |
| `projects.<ключ>.ignored_prefix` | строка | нет | Отбрасываемый префикс ([ignored prefix](../GLOSSARY.md)). |
| `projects.<ключ>.task_cache_s3` | строка | нет | Место кэша аннотаций в S3: `s3://bucket/prefix` или непустой префикс. |
| `projects.<ключ>.ignore` | список | `[]` | Список игнорируемых задач ([ignore list](../GLOSSARY.md)). Поля записи: `id` (целое ≥ 0, обязательно), `name`, `description` (строки), `silent` (`true`/`false`). Ведите его командой [`cveta2 ignore`](commands/ignore.md). |
| `projects.<ключ>.publication` | словарь | нет | Настройки публикации проекта ([publication settings](../GLOSSARY.md)). Ключ не записывается, пока блок не задан. |
| `projects.<ключ>.publication.clearml.project` | строка | обязателен в блоке | Проект ClearML, точное имя. |
| `projects.<ключ>.publication.clearml.dataset` | строка | обязателен в блоке | Датасет ClearML, точное имя. |
| `projects.<ключ>.publication.clearml.output_uri` | строка | нет | Хранилище файлов ClearML: любая схема (`s3://`, `gs://`, `azure://`, `http(s)://`, `file://`), без логина и пароля в адресе, даже если в пароле есть `/`, `?` или `#`. Пустая строка запрещена. Не записывается, пока не задан. |
| `projects.<ключ>.publication.api_url` | строка | обязателен в блоке | Адрес API классов, `http` или `https`, без логина и пароля. |
| `projects.<ключ>.publication.empty_classes` | список целых | `[]` | Исключённые классы. |
| `projects.<ключ>.publication.s3_roots` | список строк | нет | Корни S3 изображений. Без значения берётся значение по умолчанию, выведенное из облачного хранилища проекта. Не записывается, пока не задан. |
| `datasets.<ключ>` | словарь | `{}` | Управляемые датасеты. |

Неизвестный ключ в общем файле — ошибка: cveta2 не пропускает опечатки молча. Повторяющиеся ключи YAML и ссылки на себя (рекурсивные алиасы) тоже отклоняются.

### Раздел `datasets`

Каждая запись описывает управляемый датасет: источники ([source](../GLOSSARY.md)) — проекты CVAT или CSV в S3, назначение в ClearML (`clearml.project`, `clearml.dataset` и необязательный `clearml.output_uri`, по умолчанию его нет), адрес API классов (`api_url`), корни S3 изображений (`s3_roots`), исключённые классы (`empty_classes`) и решения о пересечении (`overlaps`). Источник типа `cvat` ссылается на ключ из `projects`. Все поля и правила описаны на странице [`cveta2 dataset`](commands/dataset.md).

Пары назначения ClearML (`clearml.project` и `clearml.dataset`) уникальны среди всех `projects.<ключ>.publication` и всех `datasets.<ключ>`. Повтор отклоняется с ошибкой `ClearML destination pairs must be unique: <проект>/<датасет>`.

## Локальные переопределения

Локальное переопределение ([local override](../GLOSSARY.md)) — личное значение настройки проекта, которое заменяет значение из общего файла только для вас. Например, чтобы публиковать проект `retail` в свой датасет ClearML:

```yaml
# личный файл
overrides:
  projects:
    retail:                           # тот же ключ, что в общем файле
      publication:
        clearml:
          dataset: retail-shelves-alice
```

Переопределить можно любое значение внутри `projects.<ключ>.publication`: `clearml.project`, `clearml.dataset`, `clearml.output_uri`, `api_url`, `empty_classes` и `s3_roots`. Всё остальное берётся только из общего файла: `id`, `name`, `sync_root`, `ignored_prefix`, `task_cache_s3`, список `ignore`, раздел `cvat` и раздел `datasets`. Так все в команде скачивают одни и те же данные. Другой ключ в `overrides` — ошибка `Некорректный раздел overrides личной конфигурации; поля: <ключи>`; ключ проекта, которого нет в общем файле, тоже отклоняется.

Переопределение записывает и удаляет `cveta2 setup` с `--project` и без `--global`:

| Ключ в `overrides.projects.<ключ>.publication` | Команда |
|---|---|
| `clearml.project`, `clearml.dataset`, `clearml.output_uri` | `cveta2 setup --project retail --clearml-project Retail/Datasets --dataset-name retail-shelves-alice --output-uri s3://bucket/.clearml` |
| `api_url` | `cveta2 setup --project retail --api-url https://classes.example.com/api` |
| `empty_classes`, `s3_roots` | `cveta2 setup --project retail --empty-class 5 --s3-root s3://bucket/images` |
| одно значение / весь блок | `cveta2 setup --project retail --unset dataset-name` / `cveta2 setup --project retail --unset publication` |

Удаление работает и тогда, когда общий файл переопределения не разрешает. Удаление отклоняется, только если оставшиеся переопределения стали бы некорректными (неполный блок или совпадение назначения ClearML с переопределением другого проекта) и при этом до команды они были корректны (подробнее — в [`cveta2 setup`](commands/setup.md#запись-значений)). Значения `sync_root`, `ignored_prefix` и `task_cache_s3` локально не записываются: команда отвечает ошибкой и предлагает `cveta2 setup --global`.

Значения сливаются по одному: заданное значение заменяет значение из общего файла, остальные остаются общими. В примере выше `clearml.project`, `api_url` и прочие настройки публикации берутся из общего файла. Список заменяется целиком: `empty_classes: [5]` в личном файле при `empty_classes: [12, 13]` в общем даёт `[5]`.

Все команды читают итоговую конфигурацию: общий файл плюс переопределения. Команды, которые записывают общий файл, берут за основу сам общий файл и никогда не записывают туда ваши переопределения.

### Когда переопределения разрешены

Переопределения разрешает ключ `local_overrides: true` в общем файле. Без этого ключа или с `false` личный файл, где в `overrides` задано хотя бы одно значение, отклоняется. Пустые блоки без значений (например, `retail: {}` или `publication: {}`) ничего не переопределяют и не мешают ни при каком значении `local_overrides`. Сообщение об ошибке:

```
Личная конфигурация содержит локальные переопределения (overrides.projects.retail.publication.clearml.dataset), но общая конфигурация их не разрешает. Удалите их из раздела overrides личного файла или попросите команду выполнить: cveta2 setup --global --local-overrides on
```

Исправить можно двумя способами: удалить переопределения из личного файла или попросить того, кто ведёт общий файл, разрешить их командой `cveta2 setup --global --local-overrides on`.

Раздел `overrides` допустим только в личном файле со `schema_version: 1` и подключённым общим файлом. В файле старого формата он отклоняется: `Локальные переопределения требуют личного файла со schema_version: 1 и подключённой общей конфигурацией`.

### Проверка после слияния

Правила общего файла проверяются на итоговой конфигурации. Если переопределение делает её некорректной, cveta2 останавливается с ошибкой. Так бывает в двух случаях:

- пара назначения ClearML после слияния совпадает с другим назначением из `projects.<ключ>.publication` или `datasets.<ключ>`: `Локальные переопределения делают общую конфигурацию некорректной: Value error, ClearML destination pairs must be unique: <проект>/<датасет>`;
- у проекта нет блока `publication` в общем файле, а переопределение задаёт не все обязательные значения (`clearml.project`, `clearml.dataset`, `api_url`): `Локальные переопределения делают общую конфигурацию некорректной; поля: <ключи>; <причина>`.

Настройки публикации существуют только вместе с общим файлом. Без общего файла их негде хранить и нечего переопределять: значения передаются команде `verify` флагами.

## Значения по умолчанию из пакета

В пакет встроен файл `cveta2/presets/default.yaml`:

```yaml
cvat:
  host: "http://localhost:8080"
upload:
  images_per_job: 100
  image_quality: 100
```

Из него cveta2 берёт только `cvat.host`, если адрес не задан ни в файле, ни в окружении. Значения `upload` совпадают со значениями по умолчанию в коде.

## Переменные окружения

| Переменная | Что задаёт | Что переопределяет |
|---|---|---|
| `CVETA2_CONFIG` | Путь к личному файлу. | Путь по умолчанию; флаг `--config` важнее. |
| `CVETA2_GLOBAL_CONFIG` | Путь к общему файлу. | Ключ `global_config`; флаг `--global-config` важнее. |
| `CVAT_HOST` | Адрес CVAT. | `cvat.host` из личного файла. |
| `CVAT_ORGANIZATION` | Slug организации. | `cvat.organization` из личного файла. |
| `CVAT_USERNAME` | Логин CVAT. | `cvat.username`. |
| `CVAT_PASSWORD` | Пароль CVAT. | `cvat.password`. |
| `CVETA2_DATA_TIMEOUT` | Таймаут чтения в секундах. | `cvat.request_timeout`. |
| `CVETA2_S3_WORKERS` | Целое ≥ 1. | `network.s3_workers`. |
| `CVETA2_CVAT_WORKERS` | Целое ≥ 1. | `network.cvat_workers`. |
| `CVETA2_RETRY_ATTEMPTS` | Целое ≥ 2. | `network.retry_attempts`. |
| `CVETA2_NO_INTERACTIVE` | `true` — не задавать вопросов. | См. [Неинтерактивный режим](#неинтерактивный-режим). |
| `CVETA2_DISABLE_CACHE` | `true` — не использовать кэш аннотаций. | Работает как `--no-cache` у выгрузки; `doctor` без `--cache` пропускает проверку прав кэша. |
| `CVETA2_RAISE_ON_FAILURE` | `true` — прерывать выгрузку при первой ошибке 5xx от CVAT. | Без неё задача с такой ошибкой пропускается. |
| `XDG_CACHE_HOME` | Базовый каталог кэша. | Собственный кэш cveta2 лежит в `$XDG_CACHE_HOME/cveta2`, без переменной — в `~/.cache/cveta2`. |

Значения `true` сравниваются без учёта регистра. Любое другое значение означает «выключено».

Неверное значение в `CVETA2_S3_WORKERS`, `CVETA2_CVAT_WORKERS`, `CVETA2_RETRY_ATTEMPTS` (не число или меньше минимума) или нечисловое значение в `CVETA2_DATA_TIMEOUT` не останавливает команду: cveta2 пишет предупреждение и берёт значение из файла или по умолчанию. Отрицательное число в `CVETA2_DATA_TIMEOUT` — ошибка конфигурации, команда останавливается.

```text
Некорректное значение CVETA2_S3_WORKERS='abc' — ожидается целое число; значение игнорируется.
Значение CVETA2_RETRY_ATTEMPTS=1 должно быть не меньше 2; игнорируется.
```

Доступ к S3 cveta2 получает через boto3, обычным для него способом: `AWS_ACCESS_KEY_ID` и `AWS_SECRET_ACCESS_KEY`, `~/.aws/credentials` или роль IAM. Сам cveta2 эти переменные не читает. Проверить, видит ли boto3 ключи, можно командой [`cveta2 doctor`](commands/doctor.md).

### Порядок для подключения к CVAT

Для адреса, организации, логина, пароля и таймаута: значение по умолчанию из пакета < личный файл < переменные окружения. Пустая переменная не переопределяет значение из файла.

Когда подключён общий файл, адрес и организация берутся только из него. `CVAT_HOST` и `CVAT_ORGANIZATION` при этом допустимы, только если совпадают с общим файлом. Иначе любая команда, которая читает настройки CVAT, завершается ошибкой:

```text
CVAT identity environment overrides conflict with shared project configuration
```

Уберите переменные или выберите общий файл того же сервера.

## Неинтерактивный режим

Когда аргумента не хватает, многие команды задают вопрос в терминале: логин и пароль CVAT, выбор проекта, подтверждение удаления. С `CVETA2_NO_INTERACTIVE=true` cveta2 не задаёт вопросов. Вместо вопроса команда завершается с кодом 1 и сообщением:

```text
Interactive prompt required but CVETA2_NO_INTERACTIVE=true. <подсказка, какой флаг или переменную задать>
```

Если переменная не задана, но терминала нет (например, cron или CI со стандартным вводом в конце файла), сообщение такое:

```text
Interactive prompt required but standard input is closed. <подсказка>
```

В скриптах задавайте `CVETA2_NO_INTERACTIVE=true` и передавайте все нужные значения флагами и переменными. Логин и пароль задайте в личном файле или через `CVAT_USERNAME` и `CVAT_PASSWORD`. Что именно нужно каждой команде, описано в разделе «Интерактивный и неинтерактивный режим» на её странице, например в [`cveta2 setup`](commands/setup.md#интерактивный-и-неинтерактивный-режим).

## Сеть и повторы

cveta2 повторяет сетевые операции сам. Число попыток задаёт `network.retry_attempts` (или `CVETA2_RETRY_ATTEMPTS`), это общее число попыток вместе с первой. Пауза между попытками растёт экспоненциально, начиная примерно с 1 секунды, со случайной добавкой до 1 секунды, и не превышает `network.retry_max_wait`. Если CVAT прислал заголовок `Retry-After`, cveta2 ждёт указанное время, но не дольше `retry_max_wait`. Перед каждой паузой выводится предупреждение:

```text
CVAT API: попытка cveta2 1/5 не удалась; повтор через 1.42 с: <ошибка>
```

Что повторяется:

| Операция | Когда повторяется |
|---|---|
| Чтение из CVAT | Сетевые ошибки и ответы 429, 500, 502, 503, 504. |
| Запись в CVAT | Только ответ 429. На ответ 503 cveta2 запись не повторяет: результат неизвестен, и выводится предупреждение проверить состояние в CVAT. |
| Повторяемая запись в CVAT (замена тех же значений) | Ответы 429, 500, 502, 503, 504. |
| S3 | Сетевые ошибки и коды `SlowDown`, `RequestTimeout`, `RequestTimeTooSkewed`, `InternalError`, `503`. |

Клиент S3 (boto3) дополнительно делает до 3 попыток внутри каждой попытки cveta2. Это число не настраивается.

Как настроить:

- Медленный или нестабильный канал: увеличьте `retry_attempts` и `retry_max_wait`, задайте `cvat.request_timeout`.
- CVAT отвечает 429: уменьшите `network.cvat_workers`. Если при выгрузке повторы на 429 исчерпаны, задача не пропускается, а команда останавливается и советует уменьшить `network.cvat_workers`.
- Для одного запуска используйте переменные `CVETA2_RETRY_ATTEMPTS`, `CVETA2_CVAT_WORKERS`, `CVETA2_S3_WORKERS`, `CVETA2_DATA_TIMEOUT`.

## Запись в общий файл и блокировка

Некоторые команды меняют общий файл: например, [`cveta2 ignore`](commands/ignore.md) меняет список игнорируемых задач, а [`cveta2 setup --global`](commands/setup.md#мастер-общей-настройки---global) — настройки проектов: `ignored_prefix`, `task_cache_s3`, `publication` и другие. Чтобы два человека не затёрли изменения друг друга:

1. cveta2 берёт блокировку на файл `.<имя файла>.lock` рядом с общим файлом. Если блокировку держит другой процесс, команда сразу завершается ошибкой `Cannot lock shared configuration <путь>; another writer may be active. Retry the change.` Блокировка снимается, когда процесс завершается.
2. Записываются только поля, которые изменила эта команда. Изменения других проектов от другого человека сохраняются.
3. Если то же поле кто-то изменил после того, как команда прочитала файл, запись отклоняется: `Shared configuration <путь> changed since it was loaded: project '<имя>', field <поле>; reload and repeat the change`. Повторите команду.
4. Файл заменяется атомарно, его права и группа сохраняются. Он записывается заново целиком: комментарии и оформление YAML (кавычки, порядок записи в одну строку) не сохраняются, а незаданные ключи проектов появляются со значением `null` (`sync_root`, `ignored_prefix`, `task_cache_s3`). Ключи `local_overrides`, `publication` и `output_uri` пока не заданы, в файл не записываются. Если у файла нет прав на запись ни для кого, запись отклоняется: `Shared project configuration is read-only: <путь>`.

Запись в общий файл всегда строится от самого файла, а не от эффективной конфигурации: локальное переопределение никогда не попадает в общий файл. Переопределение также не считается чужим одновременным изменением: оно не вызывает `Shared configuration ... changed since it was loaded`.

Команда `setup --global-config` общий файл не меняет никогда.

## Перенос старой конфигурации

В старом формате всё лежало в одном личном файле без `schema_version`: адрес CVAT, организация, разделы `sync_roots`, `ignore` и настройки проектов в `cache.projects`. Личный файл без `schema_version`, где есть только `cvat` (с адресом и организацией), локальные пути, `network` и `upload`, работает без общего файла. Если в нём есть `sync_roots`, `ignore`, `projects`, `datasets`, `clearml` или `ignored_prefix`/`task_cache_s3` в `cache.projects`, а также если к файлу с адресом CVAT подключён общий файл, команды останавливаются с ошибкой:

```text
Legacy mixed configuration requires verification: cveta2 setup --migrate-config
```

Перенос выполняет `cveta2 setup --migrate-config` (только в терминале):

1. cveta2 строит предложение: личный файл (логин, пароль, таймаут, локальные пути, `network`, `upload`) и общий файл (адрес, организация, проекты). Проект попадает в общий файл, только если его ID однозначно известен из `projects.yaml`.
2. Предложение выводится как JSON, логин и пароль скрыты как `<redacted>`. Общий файл по умолчанию — `project-config.yaml` рядом с личным; другой путь задаёт `--global-config`.
3. Если что-то не удалось разобрать однозначно, список проблем есть в поле `unresolved`, и команда завершается: `Сначала устраните неоднозначные настройки из отчёта миграции.`
4. После подтверждения cveta2 сохраняет копию старого файла `<имя>.pre-v1-<хеш>.bak` и записывает оба файла. Существующий общий файл с другим содержимым не перезаписывается.

Если перенос прервался, следующий запуск `setup --migrate-config` завершает его по журналу `<имя>.migration.json`. Подробности — на странице [`cveta2 setup`](commands/setup.md).

## См. также

- [`cveta2 setup`](commands/setup.md)
- [`cveta2 doctor`](commands/doctor.md)
- [Изображения и кэши](images-and-cache.md)
- [`cveta2 dataset`](commands/dataset.md)
- [Python API](python-api.md)
- [Глоссарий](../GLOSSARY.md)

# Python API

Пакет `cveta2` можно использовать из Python вместо командной строки. У каждой команды для работы с данными есть функция с тем же поведением. Её сигнатура и пример описаны в разделе «Из Python» на странице команды. Эта страница описывает общее для всех функций: подключение к CVAT, класс `CvatClient`, исключения, типы данных и функции, у которых нет своей команды.

В конце страницы есть [таблица всех имён](#все-публичные-имена) из `cveta2.__all__`.

## Импорт

```python
import cveta2
```

Все публичные имена доступны прямо из `cveta2`. Модули с CVAT SDK, ClearML и pandas загружаются только при первом обращении к имени, которому они нужны.

## Подключение к CVAT

Каждая функция, которая обращается к CVAT, принимает необязательный аргумент `connection=` типа `cveta2.Connection`.

### Connection

`Connection` — неизменяемый dataclass. Все поля необязательные.

| Поле | Тип | Что задаёт |
|---|---|---|
| `host` | `str \| None` | Адрес CVAT, например `https://cvat.example.com`. |
| `username` | `str \| None` | Логин CVAT. |
| `password` | `str \| None` | Пароль CVAT. |
| `organization` | `str \| None` | Организация CVAT, например `my-team`. Пустая строка `""` выбирает личное пространство (без организации). |
| `config_path` | `Path \| None` | Путь к файлу [личной конфигурации](../GLOSSARY.md) (personal configuration). Без него используется файл по умолчанию или `CVETA2_CONFIG`. |
| `client` | `CvatClient \| None` | Уже открытый клиент. Если он задан, функция работает через него и не открывает новое соединение. |

### Откуда берутся настройки

Если `connection` не передан или поле в нём не заполнено, значение берётся из других источников. Приоритет от высшего к низшему:

1. Поле `Connection`.
2. Переменные окружения `CVAT_HOST`, `CVAT_ORGANIZATION`, `CVAT_USERNAME`, `CVAT_PASSWORD`.
3. Секция `cvat` личной конфигурации.
4. Встроенные значения пакета. Там задан только адрес: `http://localhost:8080`.

Переменные окружения и ключи конфигурации описаны на странице [Конфигурация](configuration.md).

Если подключена [общая конфигурация](../GLOSSARY.md) (global configuration), адрес CVAT и организация берутся только из неё:

- `host` или `organization` в `Connection`, которые с ней не совпадают, вызывают `Cveta2Error` («Explicit host cannot override shared CVAT identity»).
- Клиент в `Connection.client` с другим адресом или организацией вызывает `Cveta2Error`.
- `CVAT_HOST` или `CVAT_ORGANIZATION`, которые с ней не совпадают, тоже вызывают ошибку (подкласс `Cveta2Error`).

Логин и пароль в общей конфигурации не хранятся. Они всегда берутся из `Connection`, переменных окружения или личной конфигурации.

### Пример: явные настройки

```python
import cveta2

conn = cveta2.Connection(
    host="https://cvat.example.com",
    username="user",
    password="secret",
    organization="my-team",
)
result = cveta2.fetch("Retail shelves", "output/fetch", download_images=False, connection=conn)
print(len(result.dataset), len(result.obsolete), len(result.in_progress))
```

Как и команда `cveta2 fetch`, `cveta2.fetch` пишет рядом с CSV черновик `dataset.yaml` и печатает предупреждения о его пробелах и о покрытии классов; исключений они не вызывают (см. [Черновик dataset.yaml](commands/fetch.md#черновик-datasetyaml)).

### Пример: один клиент на несколько вызовов

Без `client` каждая функция открывает своё соединение с CVAT и закрывает его в конце. Чтобы не входить в CVAT заново на каждый вызов, откройте `CvatClient` сами и передайте его через `Connection(client=...)`:

```python
import cveta2

cfg = cveta2.CvatConfig.load()
with cveta2.CvatClient(cfg) as client:
    conn = cveta2.Connection(client=client)
    project_id = client.resolve_project_id("Retail shelves")
    labels = cveta2.get_labels(project_id, connection=conn)
    rows = cveta2.fetch_task([456], "output/task", download_images=False, connection=conn)
    news = cveta2.whats_new(project_id, "output/fetch/dataset.csv", connection=conn)
```

Функция не открывает и не закрывает переданный клиент. Он должен быть открыт (`with CvatClient(...) as client:`). Если передать клиент, который не открыт, функция вызывает `Cveta2Error`:

```text
Переданный client не готов к работе: войдите в его контекст (with CvatClient(cfg) as client: ...) или создайте его с фейковым api=.
```

`config_path` из того же `Connection` по-прежнему используется для чтения конфигурации (кэш изображений, [список игнорируемых задач](../GLOSSARY.md) и так далее).

### Как указать проект

Аргумент `project` во всех функциях принимает ID (`123`), имя (`"Retail shelves"`) или `"ORG/PROJECT"`. Префикс организации заменяет организацию из настроек. `"/PROJECT"` выбирает личное пространство. Имя сравнивается без учёта регистра. Если имя совпадает у нескольких проектов, функция вызывает `Cveta2Error` и просит указать числовой ID.

## API никогда не спрашивает

Функции пакета не задают вопросов в терминале. Если команде CLI нужен ответ пользователя, в Python его заменяет аргумент или исключение:

| Что спрашивает CLI | Что происходит в Python |
|---|---|
| Адрес CVAT | Значение из источников выше. Если адрес нигде не задан, используется встроенный `http://localhost:8080`. |
| Логин и пароль | `MissingCredentialsError`. |
| Каталог для изображений | Аргумент `images_dir=` или `download_images=False`. Если ни того, ни другого нет и [кэш изображений](../GLOSSARY.md) (image cache) не настроен, `Cveta2Error`. |
| Проект или задачи из списка | Аргументы `project` и `tasks`. Не найден проект: `ProjectNotFoundError`. Не найдена задача: `TaskNotFoundError`. |
| Решения при подготовке датасета (проект ClearML, имя датасета, API классов, корни изображений) | Поля `PrepareOptions` или черновик `dataset.yaml` из `fetch`. Если решения не хватает, `MissingDecisions` со списком недостающих решений. О классах ничего не спрашивается. См. [verify](commands/verify.md#из-python). |
| Подтверждение удаления (меток, задачи) | Подтверждения нет: `update_labels(delete=...)`, `task_delete` и методы `CvatClient` сразу выполняют действие. |

`InteractiveModeRequiredError` вызывает только CLI. Это происходит, когда команде нужен ответ пользователя, а интерактивный режим выключен (`CVETA2_NO_INTERACTIVE=true`). Функции Python его не вызывают.

Функции пишут журнал (сообщения INFO и DEBUG, полосы прогресса) в stderr.

## CvatClient

`cveta2.CvatClient` — клиент CVAT, через который работают все функции.

```python
CvatClient(cfg: CvatConfig | None = None, client_factory=None, *, api: CvatApiPort | None = None)
```

- `cfg` — настройки подключения. Без него вызывается `CvatConfig.load()`.
- `api` — своя реализация `CvatApiPort` вместо настоящего CVAT, например для тестов. С `api=` клиент готов к работе без `with`.
- `client_factory` — служебный параметр, обычно его не передают.

Соединение открывается при входе в `with` и закрывается при выходе. Логин и пароль проверяются при входе: если их нет, `MissingCredentialsError`. Вызов метода, которому нужен CVAT, вне `with` даёт `RuntimeError`:

```text
list_projects() requires a context manager. Use: with CvatClient(cfg) as client: ...
```

### Свойства

| Свойство | Что возвращает |
|---|---|
| `host` | Адрес CVAT из настроек. |
| `organization` | Текущая организация сессии; `None` — личное пространство. |
| `default_organization` | Организация из настроек. |
| `is_ready` | `True`, если клиент открыт (`with`) или создан с `api=`. |
| `api` | Объект `CvatApiPort`, через который идут запросы. |

### Методы чтения

| Метод | Что делает |
|---|---|
| `list_organizations()` | Организации, в которых состоит пользователь. |
| `set_organization(org)` | Направляет следующие запросы в организацию `org`; `None` — личное пространство. |
| `list_projects()` | Все доступные проекты, список `ProjectInfo`. |
| `get_project(project_id)` | Один проект, `ProjectInfo`. |
| `resolve_project_id(project_spec)` | ID проекта по ID или имени. Число или строка из цифр возвращается как ID без запроса. |
| `find_project_by_name(name)` | `ProjectInfo` по имени без учёта регистра. Нет проекта: `ProjectNotFoundError`. Несколько: `Cveta2Error`. |
| `list_project_tasks(project_id)` | Задачи (task) проекта, список `TaskInfo`. |
| `get_task(task_id)` | Одна задача, `TaskInfo`. |
| `get_task_size(task_id)` | Число кадров (frame) задачи. |
| `get_project_labels(project_id)` | Метки (label) проекта, список `LabelInfo`. |
| `count_label_usage(project_id)` | Словарь «ID метки → число аннотаций» по всем задачам. Задачи, которые не удалось прочитать, пропускаются с предупреждением в журнале. |
| `label_usage(project_id)` | То же, плюс `skipped_task_ids` — задачи, которые не удалось прочитать, и свойство `complete`. |
| `list_new_completed_tasks(project_id, cutoff, known_task_ids)` | Задачи проекта со статусом CVAT `completed`, ID которых нет в `known_task_ids`, по возрастанию ID. `cutoff` на отбор не влияет. |
| `count_task_shapes(task_id)` | Число bbox и других фигур в задаче. |
| `count_task_label_shapes(task_id, label)` | Число фигур метки `label` в задаче. |

### Методы изменения задач

Эти методы ничего не спрашивают и сразу меняют данные в CVAT.

| Метод | Что делает |
|---|---|
| `set_task_jobs_status(task_id, *, stage=None, state=None)` | Ставит stage и/или state всем job задачи. Возвращает число job. Без `stage` и `state` — `Cveta2Error`. |
| `complete_task(task_id)` | Ставит всем job stage `acceptance` и state `completed`. Возвращает число job. |
| `delete_task(task_id)` | Удаляет задачу навсегда, вместе с данными и job. |
| `drop_label_annotations(task_id, label)` | Удаляет из задачи все фигуры метки `label`. Возвращает число удалённых. |

Для тех же действий есть функции `task_set_status`, `task_delete`, `task_drop_label`, `task_mark_deleted` (см. [task](commands/task.md#из-python)).

### Выгрузка через клиент

`prepare_fetch(project_id, *, completed_only=False, ignore_task_ids=None, silent_task_ids=None, task_selector=None, project_name="")` читает список задач и метки проекта, применяет фильтры и возвращает `FetchContext`. Затем `CvatClient.fetch_one_task(client.api, task, ctx)` выгружает одну задачу и возвращает `TaskAnnotations`, или `None`, если задача пропущена из-за ошибки CVAT 5xx. Это низкоуровневый путь: он не пишет CSV, не использует [кэш аннотаций](../GLOSSARY.md) (annotation cache) и не делит строки на файлы. Обычно удобнее `cveta2.fetch` и `cveta2.fetch_task`.

| Поле `FetchContext` | Значение |
|---|---|
| `tasks` | Задачи, отобранные для выгрузки, список `TaskInfo`. |
| `label_names` | Словарь «ID метки → имя». |
| `attr_names` | Словарь «ID атрибута → имя». |
| `host` | Адрес CVAT. |
| `project_name` | Имя проекта. |
| `raise_on_failure` | Прерывать ли выгрузку на первой ошибке 5xx (переменная `CVETA2_RAISE_ON_FAILURE`). |
| `all_task_ids` | ID всех задач проекта до фильтров, или `None`, если задачи выбирались по одной. |

У `CvatClient` есть и другие методы (создание задач, загрузка аннотаций и изображений). Их используют команды `upload` и `s3-sync`. Для своих скриптов используйте функции `cveta2.upload` и `cveta2.s3_sync`.

### CvatConfig

`cveta2.CvatConfig` — настройки подключения, которые принимает `CvatClient`.

| Поле | Тип | Значение |
|---|---|---|
| `host` | `str` | Адрес CVAT, без `/` в конце. |
| `organization` | `str \| None` | Организация; пустая строка превращается в `None`. |
| `username` | `str \| None` | Логин. |
| `password` | `str \| None` | Пароль. |
| `request_timeout` | `float \| None` | Тайм-аут запросов, секунды. В `from_env()` берётся из `CVETA2_DATA_TIMEOUT`. |

| Метод | Что делает |
|---|---|
| `CvatConfig.load(config_path=None)` | Собирает настройки из встроенных значений, личной конфигурации и переменных окружения (по возрастанию приоритета) с учётом общей конфигурации. |
| `CvatConfig.from_file(path)` | Только секция `cvat` файла. Нет файла — пустые настройки. |
| `CvatConfig.from_env()` | Только переменные окружения. |
| `cfg.merge(other)` | Новые настройки: непустые значения `other` заменяют значения `cfg`. |
| `cfg.require_credentials()` | Возвращает `cfg`, если есть логин и пароль, иначе `MissingCredentialsError`. |
| `cfg.save_to_file(path)` | Записывает секцию `cvat` в файл, остальные секции сохраняет. |

### CvatApiPort

`cveta2.CvatApiPort` — протокол (`typing.Protocol`) со всеми запросами к CVAT, которые делает `CvatClient`. Своя реализация передаётся как `CvatClient(api=...)`, например чтобы проверить скрипт без сервера.

## Исключения и предупреждения

Все исключения пакета наследуют `cveta2.Cveta2Error`. Чтобы поймать любую ошибку cveta2, достаточно `except cveta2.Cveta2Error`.

| Класс | Родитель | Когда возникает | Что содержит |
|---|---|---|---|
| `Cveta2Error` | `Exception` | Базовый класс. Сам вызывается при неверных аргументах, конфликте с общей конфигурацией, неоднозначном имени проекта или задачи и других ошибках без отдельного класса. | Текст сообщения. |
| `CvatApiError` | `Cveta2Error` | CVAT вернул ошибку, или запрос не удался после всех повторов. | `status_code`, `retry_after`, `diagnostics` (см. ниже). |
| `ProjectNotFoundError` | `Cveta2Error` | Проекта с таким именем нет. Несуществующий числовой ID обычно даёт `CvatApiError` с кодом 404. | Текст сообщения. |
| `TaskNotFoundError` | `Cveta2Error` | Задача не найдена по ID или имени. | Текст сообщения со списком доступных задач. |
| `MissingCredentialsError` | `Cveta2Error` | Нет логина или пароля CVAT. | Текст с подсказкой, где их задать. |
| `MissingHostError` | `Cveta2Error` | Адрес CVAT пустой после сбора настроек. Так как встроенные значения задают `http://localhost:8080`, при обычной установке это исключение не возникает. | Текст с подсказкой. |
| `InteractiveModeRequiredError` | `Cveta2Error` | Только в CLI: нужен ответ пользователя, а интерактивный режим выключен. | Текст с подсказкой, какой флаг или переменную использовать. |
| `LabelsMismatchError` | `Cveta2Error` | Метки из CSV не найдены в проекте. | `unknown_labels`, `available_labels`. |
| `DatasetInputError` | `Cveta2Error`, `ValueError` | CSV нельзя прочитать как таблицу, или каталог отчёта нельзя создать. | Текст сообщения. |
| `MissingDecisions` | `Cveta2Error` (через внутренний класс `UploadError`) | Подготовке датасета не хватает решений. | `decisions`: кортеж с полями `kind` (`project`, `dataset_name`, `api_url`, `local_roots`), `message`, `choices`. |
| `DatasetWarning` | `UserWarning` | Не исключение, а предупреждение модуля `warnings`: проверка датасета нашла проблему, которую можно исправить. Выдаётся при `ValidationOptions(emit_warnings=True)`. | Текст предупреждения. |

### Подробности CvatApiError

| Атрибут | Значение |
|---|---|
| `status_code` | HTTP-код ответа; `0`, если кода нет (например, сеть недоступна). |
| `retry_after` | Значение заголовка `Retry-After` в секундах или `None`. Это только подсказка о паузе. Она не доказывает, что неудавшаяся запись не была применена. |
| `diagnostics` | `CvatRequestDiagnostics` или `None`. |

Поля `diagnostics`:

| Поле | Значение |
|---|---|
| `operation` | Имя операции клиента, например `get_project_labels`. |
| `method` | HTTP-метод. |
| `endpoint` | Адрес запроса. |
| `resource_ids` | Пары «имя → ID», например `(("project_id", 123),)`. |
| `timestamp_utc` | Время ошибки, UTC. |
| `status_code` | HTTP-код. |
| `request_ids` | Пары «заголовок → ID запроса», например `X-Request-Id`. |
| `response_summary` | Краткий текст ответа CVAT. |

Текст исключения собран из этих полей. Пример для несуществующего проекта:

```text
CVAT: операция get_project_labels, GET https://cvat.example.com/api/projects/999999; HTTP 404; UTC 2026-01-01T12:00:00+00:00; project_id=999999; X-Request-Id=<id>; detail: No Project matches the given query.. Проверьте логи backend CVAT по времени и ID запроса.
```

Время и ID запроса помогают администратору CVAT найти запрос в журнале сервера.

```python
import cveta2

try:
    cveta2.get_labels(999999)
except cveta2.CvatApiError as error:
    print(error.status_code)
    if error.diagnostics is not None:
        print(error.diagnostics.endpoint, error.diagnostics.request_ids)
```

## Типы данных

### Записи аннотаций

`fetch` и `fetch_task` возвращают таблицы pandas. Их столбцы — `cveta2.CSV_COLUMNS`, в том же порядке. Каждая строка — одна запись одного из типов ниже. Значение каждого столбца описано на странице [Формат датасета](dataset-format.md).

| Имя | Что это |
|---|---|
| `CSV_COLUMNS` | Кортеж имён столбцов CSV, по порядку. |
| `BBoxAnnotation` | Один bbox; `instance_shape="box"`. Содержит все столбцы `CSV_COLUMNS`. |
| `ImageWithoutAnnotations` | Изображение без bbox; `instance_shape="none"`. Поля bbox отсутствуют. |
| `DeletedImage` | Удалённое изображение; `instance_shape="deleted"`. Попадает в `deleted.csv`. |
| `AnnotationRecord` | Тип-объединение `BBoxAnnotation \| ImageWithoutAnnotations`, вариант выбирается по `instance_shape`. |
| `ProjectAnnotations` | `annotations` (список `AnnotationRecord`) и `deleted_images` (список `DeletedImage`). Метод `to_csv_rows()` даёт словари с ключами `CSV_COLUMNS`. |
| `TaskAnnotations` | `ProjectAnnotations` одной задачи плюс `task_id`, `task_name`, `issues_complete`. `TaskAnnotations.merge(list)` объединяет результаты задач в один `ProjectAnnotations`. |

У каждой записи есть метод `to_csv_row()`: словарь с ключами `CSV_COLUMNS`. У `BBoxAnnotation` поле `attributes` в этом словаре — строка JSON.

### Проекты, задачи, метки

| Тип | Поля |
|---|---|
| `ProjectInfo` | `id`, `name`. |
| `TaskInfo` | `id`, `name`, `status` (статус задачи в CVAT, например `annotation` или `completed`), `subset`, `updated_date`, `project_id`. |
| `LabelInfo` | `id`, `name`, `color`, `attributes` (список `LabelAttributeInfo`), `type`, `svg`, `sublabels`, `project_id`, `task_id`, `parent_id`, `has_parent`. |
| `LabelAttributeInfo` | `id`, `name`, `mutable`, `input_type`, `default_value`, `values`. |
| `IgnoredTask` | Запись [списка игнорируемых задач](../GLOSSARY.md): `id`, `name`, `description`, `silent`. |

### Значения job и split

| Имя | Значение |
|---|---|
| `JobStage` | Тип: `"annotation"`, `"validation"`, `"acceptance"`. |
| `JOB_STAGES` | Кортеж `("annotation", "validation", "acceptance")`. |
| `JobState` | Тип: `"new"`, `"in progress"`, `"completed"`, `"rejected"`. |
| `JOB_STATES` | Кортеж `("new", "in progress", "completed", "rejected")`. |
| `Split` | Тип: `"train"`, `"val"`, `"test"`. |

### Результаты функций

| Тип | Кто возвращает | Поля |
|---|---|---|
| `PartitionResult` | `fetch`, `partition_annotations_df` | См. [ниже](#partition_annotations_df). |
| `UploadResult` | `upload` | `task_id`, `task_name`, `url`, `images`, `deleted`, `annotations`, `issues`. См. [upload](commands/upload.md#из-python). |
| `WhatsNewResult` | `whats_new` | `tasks` (список `TaskInfo`), `cutoff` (наибольший ID завершённой задачи в `dataset.csv`; если завершённых нет, наибольший ID вообще). См. [whats-new](commands/whats-new.md#из-python). |
| `ValidationResult` | `verify`, `verify_dataframe` | См. [ниже](#validationresult). |
| `PreparedDataset` | `prepare_dataset` | `directory`, `ready`, `validation`, `metadata`, `tasks`, `blockers`, `pending`, `changes`, `mark_changes`, `dropped_local_roots`, `split_prefilled`, `parent`. См. [verify](commands/verify.md#из-python). |
| `Publication` | `upload_dataset`, `publish_dataset` | `dataset_id`, `version`. См. [upload-dataset](commands/upload-dataset.md#из-python). |

### Параметры проверки

| Тип | Значение |
|---|---|
| `Profile` | [Профиль проверки](../GLOSSARY.md) (verification profile): `"cveta2"` или `"clearml-yolo"`. |
| `ValidationOptions` | Параметры проверки: `iou_threshold=0.99`, `check_images=False`, `image_root=None`, `base_dir=None`, `emit_warnings=True`. Неизвестное поле — ошибка. Подробнее: [verify](commands/verify.md#из-python). |
| `Issue` | Одна находка проверки: `code`, `message`, `severity` (`"error"` или `"warning"`), `row_position` (номер строки входа с нуля), `columns`, `related_rows`, `iou`. |
| `PrepareOptions` | Параметры подготовки датасета. Подробнее: [verify](commands/verify.md#из-python). |

#### ValidationResult

| Поле или метод | Значение |
|---|---|
| `profile` | Профиль, по которому шла проверка. |
| `clean` | Предлагаемые строки после удаления отклонённых и исправлений (DataFrame). |
| `broken` | [Отклонённые строки](../GLOSSARY.md) (broken rows) без изменений (DataFrame). |
| `clean_row_positions`, `broken_row_positions` | Номера исходных строк с нуля. |
| `issues` | Все находки, кортеж `Issue`. |
| `input_row_count` | Число строк на входе. |
| `input_image_count`, `clean_image_count` | Число изображений на входе и в `clean`. |
| `checked_checks`, `skipped_checks` | Какие проверки выполнены и какие пропущены. |
| `structural_errors` | `True`, если таблица целиком не подходит (например, нет обязательных столбцов). |
| `is_valid` | `True`, если нет ни отклонённых строк, ни структурных ошибок. |
| `requires_cleanup` | `True`, если есть отклонённые строки или исправления (`bbox_clipped`, `class_canonicalized`), которые нужно подтвердить. |
| `warnings` | Находки с `severity="warning"`. |
| `reasons_for(row_position)` | Все находки для одной исходной строки. |

## Функции без отдельной команды

### verify_dataframe

Проверяет таблицу в памяти, ничего не пишет на диск. Сигнатура и параметры — на странице [verify](commands/verify.md#из-python).

```python
import pandas as pd
import cveta2

frame = pd.read_csv("output/fetch/dataset.csv")
result = cveta2.verify_dataframe(frame, options=cveta2.ValidationOptions(emit_warnings=False))
print(result.is_valid, result.requires_cleanup, len(result.clean), len(result.broken))
```

### schema_for

```python
cveta2.schema_for(profile: Profile) -> pandera.DataFrameSchema
```

Возвращает схему pandera для профиля проверки. Схема не приводит типы и не удаляет лишние столбцы. Обязательные столбцы:

| Профиль | Обязательные столбцы |
|---|---|
| `cveta2` | `image_name`, `image_width`, `image_height`, `instance_shape`, `instance_label`, `bbox_x_tl`, `bbox_y_tl`, `bbox_x_br`, `bbox_y_br` |
| `clearml-yolo` | `image_name`, `image_path`, `instance_label`, `bbox_x_tl`, `bbox_y_tl`, `bbox_x_br`, `bbox_y_br`, `split` |

```python
import cveta2

schema = cveta2.schema_for("clearml-yolo")
required = [name for name, column in schema.columns.items() if column.required]
```

Схема описывает только столбцы и значения отдельных ячеек. Полную проверку (дубликаты, IoU, границы изображения) делают `verify` и `verify_dataframe`.

### partition_annotations_df

```python
cveta2.partition_annotations_df(df: pd.DataFrame, deleted_images: list[DeletedImage]) -> PartitionResult
```

Делит таблицу аннотаций на части так же, как [полная выгрузка](../GLOSSARY.md) (full fetch). В `df` обязательны столбцы `image_name`, `task_id`, `job_stage`, `job_state`. Правила разбиения описаны на странице [Формат датасета](dataset-format.md). Функция ничего не пишет на диск и не обращается к CVAT.

| Поле `PartitionResult` | Значение |
|---|---|
| `dataset` | Строки датасета (`dataset.csv`), DataFrame. |
| `obsolete` | [Устаревшие аннотации](../GLOSSARY.md) (obsolete), DataFrame. |
| `in_progress` | Строки [в работе](../GLOSSARY.md) (in progress), DataFrame. |
| `deleted_images` | [Удалённые изображения](../GLOSSARY.md) (deleted image), список `DeletedImage`. |
| `pending_deletions` | [Отложенные удаления](../GLOSSARY.md) (pending deletion), список `DeletedImage`. |
| `reopened_deletions` | [Переоткрытые удаления](../GLOSSARY.md) (reopened deletion), список `DeletedImage`. |

При записи `in_progress.csv` команда `fetch` добавляет к `in_progress` строки из `pending_deletions` и `reopened_deletions`.

Пример: заново разбить строки, выгруженные `fetch_task`.

```python
import cveta2

rows = cveta2.fetch_task([456, 457], "output/tasks", project="Retail shelves", download_images=False)
parts = cveta2.partition_annotations_df(rows, [])
print(len(parts.dataset), len(parts.obsolete), len(parts.in_progress))
```

Здесь список удалённых изображений пустой: `fetch_task` возвращает только строки аннотаций, а удалённые изображения пишет в `deleted.csv`. Такое разбиение не учитывает удаления, поэтому результат может отличаться от полной выгрузки: удалённое изображение остаётся в `dataset`, а задача, в незавершённом job которой все кадры удалены, считается завершённой. Если удаления важны, используйте [`cveta2.fetch`](commands/fetch.md#из-python): он учитывает их сам и возвращает готовый `PartitionResult`.

## Все публичные имена

| Имя | Где описано |
|---|---|
| `CSV_COLUMNS` | [Записи аннотаций](#записи-аннотаций) |
| `JOB_STAGES` | [Значения job и split](#значения-job-и-split) |
| `JOB_STATES` | [Значения job и split](#значения-job-и-split) |
| `AnnotationRecord` | [Записи аннотаций](#записи-аннотаций) |
| `BBoxAnnotation` | [Записи аннотаций](#записи-аннотаций) |
| `Connection` | [Connection](#connection) |
| `CvatApiError` | [Подробности CvatApiError](#подробности-cvatapierror) |
| `CvatApiPort` | [CvatApiPort](#cvatapiport) |
| `CvatClient` | [CvatClient](#cvatclient) |
| `CvatConfig` | [CvatConfig](#cvatconfig) |
| `Cveta2Error` | [Исключения и предупреждения](#исключения-и-предупреждения) |
| `DatasetInputError` | [Исключения и предупреждения](#исключения-и-предупреждения) |
| `DatasetWarning` | [Исключения и предупреждения](#исключения-и-предупреждения) |
| `DeletedImage` | [Записи аннотаций](#записи-аннотаций) |
| `FetchContext` | [Выгрузка через клиент](#выгрузка-через-клиент) |
| `IgnoredTask` | [Проекты, задачи, метки](#проекты-задачи-метки) |
| `ImageWithoutAnnotations` | [Записи аннотаций](#записи-аннотаций) |
| `InteractiveModeRequiredError` | [Исключения и предупреждения](#исключения-и-предупреждения) |
| `Issue` | [Параметры проверки](#параметры-проверки) |
| `JobStage` | [Значения job и split](#значения-job-и-split) |
| `JobState` | [Значения job и split](#значения-job-и-split) |
| `LabelAttributeInfo` | [Проекты, задачи, метки](#проекты-задачи-метки) |
| `LabelInfo` | [Проекты, задачи, метки](#проекты-задачи-метки) |
| `LabelsMismatchError` | [Исключения и предупреждения](#исключения-и-предупреждения) |
| `MissingCredentialsError` | [Исключения и предупреждения](#исключения-и-предупреждения) |
| `MissingDecisions` | [Исключения и предупреждения](#исключения-и-предупреждения), [verify](commands/verify.md#из-python) |
| `MissingHostError` | [Исключения и предупреждения](#исключения-и-предупреждения) |
| `PartitionResult` | [partition_annotations_df](#partition_annotations_df) |
| `PrepareOptions` | [verify](commands/verify.md#из-python) |
| `PreparedDataset` | [verify](commands/verify.md#из-python) |
| `Profile` | [Параметры проверки](#параметры-проверки) |
| `ProjectAnnotations` | [Записи аннотаций](#записи-аннотаций) |
| `ProjectInfo` | [Проекты, задачи, метки](#проекты-задачи-метки) |
| `ProjectNotFoundError` | [Исключения и предупреждения](#исключения-и-предупреждения) |
| `Publication` | [upload-dataset](commands/upload-dataset.md#из-python), [dataset](commands/dataset.md) |
| `Split` | [Значения job и split](#значения-job-и-split) |
| `TaskAnnotations` | [Записи аннотаций](#записи-аннотаций) |
| `TaskInfo` | [Проекты, задачи, метки](#проекты-задачи-метки) |
| `TaskNotFoundError` | [Исключения и предупреждения](#исключения-и-предупреждения) |
| `UploadResult` | [upload](commands/upload.md#из-python) |
| `ValidationOptions` | [verify](commands/verify.md#из-python) |
| `ValidationResult` | [ValidationResult](#validationresult) |
| `WhatsNewResult` | [whats-new](commands/whats-new.md#из-python) |
| `compare_datasets` | [dataset diff](commands/dataset.md#diff) |
| `convert_from_yolo` | [convert](commands/convert.md#из-python) |
| `convert_to_coco` | [convert](commands/convert.md#из-python) |
| `convert_to_yolo` | [convert](commands/convert.md#из-python) |
| `dataset_versions` | [dataset versions](commands/dataset.md#versions) |
| `fetch` | [fetch](commands/fetch.md#из-python) |
| `fetch_dataset` | [dataset fetch](commands/dataset.md#fetch) |
| `fetch_task` | [fetch-task](commands/fetch-task.md#из-python) |
| `get_labels` | [labels](commands/labels.md#из-python) |
| `ignore` | [ignore](commands/ignore.md#из-python) |
| `list_datasets` | [dataset list](commands/dataset.md#list) |
| `merge` | [merge](commands/merge.md#из-python) |
| `partition_annotations_df` | [partition_annotations_df](#partition_annotations_df) |
| `prepare_dataset` | [verify](commands/verify.md#из-python) |
| `prepare_managed_dataset` | [dataset prepare](commands/dataset.md#prepare) |
| `publish_dataset` | [dataset publish](commands/dataset.md#publish) |
| `report_dataset_errors` | [dataset report-errors](commands/dataset.md#report-errors) |
| `s3_sync` | [s3-sync](commands/s3-sync.md#из-python) |
| `schema_for` | [schema_for](#schema_for) |
| `show_dataset` | [dataset show](commands/dataset.md#show) |
| `task_delete` | [task](commands/task.md#из-python) |
| `task_drop_label` | [task](commands/task.md#из-python) |
| `task_mark_deleted` | [task](commands/task.md#из-python) |
| `task_set_status` | [task](commands/task.md#из-python) |
| `update_labels` | [labels](commands/labels.md#из-python) |
| `upload` | [upload](commands/upload.md#из-python) |
| `upload_dataset` | [upload-dataset](commands/upload-dataset.md#из-python) |
| `verify` | [verify](commands/verify.md#из-python) |
| `verify_dataframe` | [verify_dataframe](#verify_dataframe) |
| `whats_new` | [whats-new](commands/whats-new.md#из-python) |

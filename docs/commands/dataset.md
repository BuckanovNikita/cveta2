# cveta2 dataset

Работает с управляемыми датасетами ([managed dataset](../../GLOSSARY.md)): выгружает их источники, готовит проверенный датасет из вашего преобразованного CSV, отправляет замечания в CVAT и публикует новую версию в ClearML. Всё, что нужно для этого, кроме вашего преобразования, описано по имени датасета в общей конфигурации ([global configuration](../../GLOSSARY.md)).

> **Внимание.** `dataset publish` создаёт в ClearML новую финализированную версию датасета. cveta2 не умеет её удалить или отменить. `dataset report-errors` и `dataset publish` создают issue в задачах (task) CVAT; cveta2 их не удаляет.

## Примеры

Посмотреть, какие датасеты описаны в общей конфигурации:

```bash
cveta2 dataset list
```

Выгрузить источники датасета `shelves-det`, затем подготовить его из вашего CSV и опубликовать:

```bash
cveta2 dataset fetch shelves-det --output-dir output/fetch
# ... ваше преобразование: output/fetch/dataset.csv -> output/transformed.csv
cveta2 dataset prepare shelves-det output/transformed.csv --source output/fetch --output-dir output/prepared
cveta2 dataset report-errors output/prepared
cveta2 dataset publish output/prepared
```

Сравнить две опубликованные версии по их ID в ClearML или два локальных каталога:

```bash
cveta2 dataset diff 1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6 7f6e5d4c3b2a41908f7e6d5c4b3a2910
cveta2 dataset diff output/prepared-v1 output/prepared-v2
```

## Описание датасета в общей конфигурации

Управляемый датасет описывается в разделе `datasets` общей конфигурации. Ключ записи (`shelves-det` ниже) — это имя, которое вы передаёте командам. Остальные разделы файла описаны в [configuration.md](../configuration.md).

```yaml
schema_version: 1
cvat:
  host: https://cvat.example.com
  organization: my-team
projects:
  shelves:
    id: 123
    name: Retail shelves
    ignore:
      - id: 456
        description: тестовая задача
datasets:
  shelves-det:
    sources:
      - name: cvat
        type: cvat
        project: shelves
      - name: extra
        type: s3-csv
        uri: s3://my-bucket/annotations/extra.csv
    clearml:
      project: Retail/Datasets
      dataset: shelves-det
    api_url: https://classes.example.com/api/classes
    s3_roots:
      - s3://my-bucket/images
    empty_classes: [12]
    overlaps:
      <SHA-256 содержимого изображения>:
        source: cvat
        members: [cvat, extra]
```

Ключи проектов и датасетов: латинские буквы, цифры, `_` и `-`, первым символом буква или цифра. Неизвестный ключ в записи — ошибка.

| Ключ | Обязателен | По умолчанию | Описание |
|---|---|---|---|
| `sources` | да | — | Список источников ([source](../../GLOSSARY.md)), минимум один. Имена источников и их ссылки не должны повторяться. |
| `sources[].name` | да | — | Имя источника: латинские буквы, цифры, `_`, `-`. Оно попадает в столбец `source_id` и в каталог `sources/<name>/`. |
| `sources[].type` | да | — | `cvat` — проект CVAT; `s3-csv` — один CSV-файл в S3. |
| `sources[].project` | для `cvat` | — | Ключ проекта из раздела `projects`. Для `s3-csv` не указывается. |
| `sources[].uri` | для `s3-csv` | — | Точный адрес объекта `s3://bucket/key.csv`. Ключ должен оканчиваться на `.csv`. Для `cvat` не указывается. |
| `clearml.project` | да | — | Проект ClearML. Сравнивается точно, без поиска во вложенных проектах. |
| `clearml.dataset` | да | — | Имя датасета в ClearML. Пара `project` + `dataset` не должна повторяться у разных датасетов. |
| `api_url` | да | — | Адрес API реестра классов ([class registry](../../GLOSSARY.md)), `http://` или `https://` без логина и пароля в адресе. |
| `s3_roots` | нет | `[]` | Корни S3, в которых должны лежать изображения из столбца `s3_image_path`. При подготовке и публикации cveta2 проверяет, что каждый корень доступен для чтения списка объектов. |
| `empty_classes` | нет | `[]` | Номера классов (`prod_id`, [class identity](../../GLOSSARY.md)), исключённых из обучения ([empty class](../../GLOSSARY.md)). Строка с таким классом отклоняется с кодом `empty_class`. Номер, которого нет в реестре классов, — ошибка. |
| `overlaps` | нет | `{}` | Решения о пересечении ([overlap decision](../../GLOSSARY.md)). Ключ — SHA-256 содержимого изображения, которое пришло из нескольких источников. |
| `overlaps.<sha256>.members` | да | — | Точный список источников, в которых найдено это изображение. |
| `overlaps.<sha256>.source` | нет | `null` | Источник, строки которого остаются. `null` исключает изображение из датасета целиком. |

Для источника `cvat` также действует список игнорируемых задач ([ignore list](../../GLOSSARY.md)) проекта (`projects.<ключ>.ignore`): эти задачи выгрузка пропускает.

### Вся цепочка

```text
dataset fetch          -> каталог выгрузки: dataset.csv, sources/, source-snapshot.yaml
ваше преобразование    -> свой CSV (заполнить image_path, выбрать строки, поправить классы)
dataset prepare        -> подготовленный датасет: report.json, broken-images.csv, при готовности dataset.csv, dataset.yaml, tasks.yaml
dataset report-errors  -> issue в CVAT на кадрах с ошибками
dataset publish        -> новая версия в ClearML
```

1. `fetch` читает все источники и пишет каталог выгрузки управляемого датасета.
2. Вы преобразуете `dataset.csv` из этого каталога любым своим кодом и сохраняете результат в отдельный файл.
3. `prepare` переносит опубликованный split, проверяет строки и изображения и пишет новый каталог подготовленного датасета ([prepared bundle](../../GLOSSARY.md)).
4. `report-errors` отправляет замечания к кадрам ([feedback finding](../../GLOSSARY.md)) в CVAT. Этот шаг можно пропустить: `publish` всё равно доставит замечания перед загрузкой.
5. `publish` перепроверяет подготовку и загружает три файла новой версией в ClearML.

Управляемая история датасета начинается с первой версии. Если в `clearml.dataset` ещё нет версий, первая подготовка и публикация делаются как обычно. Если там уже есть версии, сделанные не через `dataset publish` (например, через `upload-dataset`), первую управляемую версию подготовьте с флагом `--first`: см. [prepare](#prepare).

## Общие аргументы

Все восемь операций принимают эти флаги:

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `--config` | `CVETA2_CONFIG` или `~/.config/cveta2/config.yaml` | Путь к личной конфигурации ([personal configuration](../../GLOSSARY.md)). |
| `--global-config` | `CVETA2_GLOBAL_CONFIG`, иначе `global_config` из личной конфигурации | Путь к общей конфигурации. Подробно о выборе файла — в [configuration.md](../configuration.md). |
| `--json` | выключен | Принимается, но ничего не меняет: результат всегда печатается в JSON. |

Результат каждой операции печатается в стандартный вывод в JSON. Сообщения об ошибках идут в журнал (stderr). ClearML SDK может печатать свои строки (предупреждения, ход загрузки) в стандартный вывод перед JSON. Например, пока в проекте ClearML нет ни одного датасета, он печатает `No projects were found with name(s): ...`; это не ошибка. Если вы разбираете вывод в скрипте, удобнее вызывать функции из Python (см. разделы «Из Python»).

### Коды завершения

| Код | Когда |
|---|---|
| `0` | Операция выполнена. Для `prepare` — подготовка готова к публикации. |
| `1` | Только `prepare`: каталог записан, но есть блокирующие условия (`"ready": false`). |
| `2` | Ошибка операции: конфигурация, сеть, CVAT, S3, ClearML, изменившиеся источники и т. п. Для `report-errors` — также если хотя бы одно замечание не доставлено. Также неверные аргументы командной строки. |

### Интерактивный и неинтерактивный режим

Команда `dataset` ничего не спрашивает в терминале и одинаково работает при `CVETA2_NO_INTERACTIVE=true`. Все обязательные аргументы нужно передать явно, иначе команда завершается с кодом `2` и сообщением argparse.

### Ошибки конфигурации

Эти ошибки возможны у любой операции:

| Сообщение | Причина и решение |
|---|---|
| `Ошибка операции с набором данных: Unknown managed dataset: <имя>` | В разделе `datasets` нет такого ключа. Проверьте имя через `cveta2 dataset list`. |
| `Ошибка операции с набором данных: Invalid shared project configuration <путь>; fields: datasets.<имя>.sources.<номер>` | У источника `cvat` нет `project` или задан `uri`; у `s3-csv` адрес не вида `s3://bucket/key.csv`. |

## list

### Синтаксис и аргументы

```text
cveta2 dataset list [--config CONFIG] [--global-config GLOBAL_CONFIG] [--json]
```

Только общие аргументы.

### Как это работает

1. Читает общую конфигурацию.
2. Печатает все записи `datasets`, отсортированные по имени. В сеть не обращается.

### Результат

Список объектов: `name` и все ключи записи с подставленными значениями по умолчанию.

```json
[
  {
    "name": "shelves-det",
    "sources": [
      {"name": "cvat", "type": "cvat", "project": "shelves", "uri": null},
      {"name": "extra", "type": "s3-csv", "project": null, "uri": "s3://my-bucket/annotations/extra.csv"}
    ],
    "clearml": {"project": "Retail/Datasets", "dataset": "shelves-det"},
    "api_url": "https://classes.example.com/api/classes",
    "s3_roots": ["s3://my-bucket/images"],
    "empty_classes": [],
    "overlaps": {}
  }
]
```

### Из Python

```python
cveta2.list_datasets(*, config_path: Path | None = None, project_config: Path | None = None) -> list[dict[str, Any]]
```

```python
import cveta2

print([d["name"] for d in cveta2.list_datasets()])
```

## show

### Синтаксис и аргументы

```text
cveta2 dataset show [--config CONFIG] [--global-config GLOBAL_CONFIG] [--json] name
```

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `name` | обязателен | Имя датасета из раздела `datasets`. |

### Как это работает

1. Читает запись датасета из общей конфигурации.
2. Ищет в ClearML последнюю финализированную версию с точно таким `clearml.project` и `clearml.dataset` — родительский датасет ([parent dataset](../../GLOSSARY.md)). Её `dataset.yaml` не читается, поэтому версия без управляемых метаданных тоже показывается.

### Результат

```json
{
  "name": "shelves-det",
  "definition": { "sources": [], "clearml": {}, "...": "та же запись, что в list" },
  "parent_id": "7f6e5d4c3b2a41908f7e6d5c4b3a2910",
  "parent_version": "1.0.1"
}
```

Если версий ещё нет, `parent_id` и `parent_version` равны `null`.

### Из Python

```python
cveta2.show_dataset(name: str, *, config_path: Path | None = None, project_config: Path | None = None) -> dict[str, Any]
```

## versions

### Синтаксис и аргументы

```text
cveta2 dataset versions [--config CONFIG] [--global-config GLOBAL_CONFIG] [--json] name
```

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `name` | обязателен | Имя датасета из раздела `datasets`. |

### Как это работает

Читает из ClearML финализированные и не архивированные версии датасета в точном проекте `clearml.project` с именем `clearml.dataset`.

### Результат

```json
[
  {
    "id": "1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6",
    "project": "Retail/Datasets",
    "name": "shelves-det",
    "version": "1.0.0",
    "created": "2026-11-20 11:44:17.085000+00:00"
  }
]
```

Пока версий нет — пустой список `[]`.

### Из Python

```python
cveta2.dataset_versions(name: str, *, config_path: Path | None = None, project_config: Path | None = None) -> list[dict[str, str | None]]
```

## fetch

Собирает исходные данные всех источников датасета в новый каталог — каталог выгрузки управляемого датасета. Этот каталог потом передаётся в `prepare` через `--source`.

### Синтаксис и аргументы

```text
cveta2 dataset fetch [--config CONFIG] [--global-config GLOBAL_CONFIG] [--json]
                     --output-dir OUTPUT_DIR [--refresh] name
```

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `name` | обязателен | Имя датасета из раздела `datasets`. |
| `--output-dir` | обязателен | Новый каталог выгрузки. Он не должен существовать. |
| `--refresh` | выключен | Не брать задачи из опубликованной версии, а прочитать аннотации всех задач CVAT заново. |

### Как это работает

1. Читает запись датасета и загружает реестр классов с `api_url`.
2. Ищет последнюю версию в ClearML. Если она управляемая (её `dataset.yaml` читается и содержит блок `managed`), это родительский датасет: из его `tasks.yaml` берётся снимок источников ([source snapshot](../../GLOSSARY.md)) прошлой публикации. Из неуправляемой версии не читается ничего, даже `tasks.yaml`, и все задачи читаются заново. Если `dataset.yaml` не читается, команда ещё пишет предупреждение `dataset.yaml последней версии <id> не читается, источники выгружаются заново: ...`.
3. Для каждого источника `cvat`:
   1. Читает метки (label) проекта и список его задач. Задача считается завершённой ([completed task](../../GLOSSARY.md)), если её статус `completed`, у неё есть job и каждый job в stage `acceptance` и state `completed`.
   2. Пропускает задачи из списка игнорируемых задач проекта.
   3. Решает для каждой задачи: взять её из прошлой публикации или прочитать заново (см. ниже).
   4. Из всех задач источника заново строит четыре таблицы, как при полной выгрузке ([full fetch](../../GLOSSARY.md)): `dataset.csv`, `obsolete.csv`, `in_progress.csv`, `deleted.csv`.
4. Для каждого источника `s3-csv` читает CSV-объект целиком и запоминает SHA-256 содержимого, ETag и версию объекта. В CSV должны быть столбцы `image_name`, `image_path`, `instance_label`, `bbox_x_tl`, `bbox_y_tl`, `bbox_x_br`, `bbox_y_br` и не должно быть столбцов `source_*` (см. ниже). Его строки целиком становятся `dataset.csv` источника, остальные три таблицы пустые. Изображения из S3 не скачиваются.
5. Объединяет `dataset.csv` всех источников в общий `dataset.csv` и добавляет к каждой строке столбцы происхождения.
6. Пишет каталог. Если каталог уже существует, команда завершается ошибкой — но только после того, как все источники прочитаны.

Ничего не меняет в CVAT, S3 и ClearML.

#### Когда задачи берутся из прошлой публикации

Задача CVAT берётся из снимка последней опубликованной версии без чтения аннотаций, если выполнено всё:

- в прошлой версии и сейчас задача завершена;
- её время изменения (`updated_date`) не изменилось;
- у источника то же имя, тот же тип и тот же ID проекта, а метки проекта не менялись.

Все задачи читаются заново, если:

- передан `--refresh`;
- опубликованной версии ещё нет;
- изменился реестр классов;
- изменился адрес CVAT (`cvat.host`) или организация;
- прошлая версия опубликована старой версией cveta2 без полного снимка источников.

Незавершённые задачи читаются всегда. Источник `s3-csv` читается всегда. Повторный `fetch` в другой каталог без публикации между ними читает всё заново: cveta2 берёт задачи только из опубликованной версии в ClearML, а не из прошлых локальных каталогов.

Какие задачи прочитаны, а какие взяты из прошлой версии, видно в выводе: поля `fetched` и `reused`.

### Результат

Каталог выгрузки:

```text
output/fetch/
├── dataset.csv              строки dataset.csv всех источников со столбцами происхождения
├── source-snapshot.yaml     снимок источников
└── sources/
    ├── cvat/                dataset.csv, obsolete.csv, in_progress.csv, deleted.csv
    └── extra/               dataset.csv, obsolete.csv, in_progress.csv, deleted.csv
```

Столбцы CSV описаны в [dataset-format.md](../dataset-format.md). `fetch` добавляет к общему `dataset.csv` столбцы происхождения:

| Столбец | Значение |
|---|---|
| `source_id` | Имя источника. |
| `source_project_id` | ID проекта CVAT; пусто для `s3-csv`. |
| `source_task_id` | ID задачи CVAT (копия `task_id`); пусто для `s3-csv`. |
| `source_frame_id` | Номер кадра (frame) в задаче (копия `frame_id`); пусто для `s3-csv`. |
| `source_row_id` | Идентификатор строки: `<источник>:<SHA-256 строки>:<номер повтора>`. |

У строк из CVAT столбец `image_path` пустой: путь к локальному файлу заполняете вы при преобразовании.

`source-snapshot.yaml` хранит реестр классов, адрес и организацию CVAT, метки CVAT, по каждой задаче её время изменения, признак завершённости и исходные таблицы, а для `s3-csv` — адрес, SHA-256, ETag и версию объекта. Этот снимок потом попадает в опубликованный `tasks.yaml`.

Вывод:

```json
{
  "directory": "output/fetch",
  "rows": 12,
  "parent_id": "1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6",
  "excluded_class_rows": 0,
  "missing_classes": [],
  "sources": [
    {"name": "cvat", "fetched": [457], "reused": [456], "content_hash": null},
    {"name": "extra", "fetched": [], "reused": [], "content_hash": "130da2ad...86d0"}
  ]
}
```

`rows` — число строк общего `dataset.csv`, `parent_id` — ID родительского датасета или `null`.

`excluded_class_rows` — число строк с классами из `empty_classes`, `missing_classes` — классы, которые не исключены и не имеют ни одного bbox ни в одном split (строка с меткой и пустой формой тоже считается bbox). Оба поля считаются по реестру классов из API; если реестр построить нельзя (например, номер из `empty_classes` отсутствует в API или классы последней управляемой версии не сходятся с API), поля равны `null`. `fetch` предупреждает в журнале:

- `Строк с исключёнными классами: <N>. dataset prepare отклонит их.`;
- `Нет ни одного bbox у классов: <имена>. Добавьте данные с ними или исключите класс через empty_classes.`;
- `Не удалось проверить классы: <причина>` (одно предупреждение).

Эта проверка никогда не останавливает `fetch` и не меняет код возврата: блокирует только `prepare`, а `publish` откажет. Классы последней версии читаются, только если она управляемая.

### Частые ошибки

| Сообщение | Причина и решение |
|---|---|
| `Candidate directory already exists: <каталог>` | Каталог `--output-dir` уже есть. Укажите новый. |
| `Cannot read required S3 CSV source: s3://...` | Объект `s3-csv` не читается: нет файла, нет доступа или не настроены учётные данные S3. |
| `S3 annotation CSV lacks required columns: [...]` | В CSV источника `s3-csv` нет обязательных столбцов. |
| `Source CSV contains reserved provenance columns: [...]` | В CSV источника `s3-csv` уже есть столбцы `source_*`. Уберите их из файла. |
| `Task changed during fetch: <источник>/<задача>` | Задачу меняли во время чтения. Запустите `fetch` ещё раз. |

### Из Python

```python
cveta2.fetch_dataset(
    name: str,
    *,
    output_dir: Path,
    refresh: bool = False,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> dict[str, Any]
```

Возвращает тот же словарь, что печатает команда.

```python
from pathlib import Path
import cveta2

result = cveta2.fetch_dataset("shelves-det", output_dir=Path("output/fetch"))
print(result["rows"], [s["reused"] for s in result["sources"]])
```

## prepare

Управляемая подготовка ([managed preparation](../../GLOSSARY.md)): переносит опубликованный split, проверяет ваш преобразованный CSV и изображения и пишет новый каталог подготовленного датасета. Ничего не меняет в CVAT, S3 и ClearML.

### Синтаксис и аргументы

```text
cveta2 dataset prepare [--config CONFIG] [--global-config GLOBAL_CONFIG] [--json]
                       --output-dir OUTPUT_DIR --source SOURCE [--no-clean] [--first]
                       name csv
```

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `name` | обязателен | Имя датасета из раздела `datasets`. |
| `csv` | обязателен | Ваш преобразованный CSV. |
| `--source` | обязателен | Каталог выгрузки от `dataset fetch` (или путь к его `source-snapshot.yaml`). |
| `--output-dir` | обязателен | Новый каталог подготовки. Не должен существовать и не должен лежать внутри каталога `--source`. |
| `--no-clean` | выключен | Не принимать очистку ([cleanup acceptance](../../GLOSSARY.md)). По умолчанию отклонённые строки удаляются, а исправления применяются; с `--no-clean` подготовка блокируется, если очистка нужна. |
| `--clean` | — | Оставлен для совместимости: очистка и так включена по умолчанию. |
| `--first` | выключен | Начать управляемую историю датасета: подготовить первую управляемую версию, хотя в ClearML уже есть версии без управляемых метаданных. Последняя версия не используется: ни её классы, ни split, ни строки. `publish` создаст версию без родителя. Если последняя версия уже управляемая, флаг отклоняется. Версия без `dataset.yaml` или с `dataset.yaml`, который не читается, считается неуправляемой; команда пишет предупреждение `dataset prepare --first: последняя версия <id> считается неуправляемой (<причина>)`. |

### Что должен содержать преобразованный CSV

Преобразование — ваш код: вы можете убрать строки, оставить одну аннотацию на изображение, переименовать классы, поправить координаты. cveta2 не проверяет, как CSV получен, но требует:

- уникальные непустые имена столбцов;
- столбцы профиля проверки ([verification profile](../../GLOSSARY.md)) `clearml-yolo`: `image_name`, `image_path`, `instance_label`, `bbox_x_tl`, `bbox_y_tl`, `bbox_x_br`, `bbox_y_br`. Столбец `split` заполняете вы для новых изображений; у изображений, уже опубликованных в родительской версии, cveta2 запишет опубликованный split;
- в `image_path` у каждой строки путь к локальному файлу изображения. Файл должен лежать внутри разрешённых локальных корней: `cache.images_root` личной конфигурации и каталогов кэша изображений проектов-источников (см. [images-and-cache.md](../images-and-cache.md)). Изображение должно читаться: cveta2 считает SHA-256 его содержимого;
- если есть столбец `s3_image_path`, каждый непустой путь должен лежать ровно в одном из корней `s3_roots`;
- одно и то же `image_name` не может указывать на изображения с разным содержимым;
- чтобы ошибку можно было отправить в CVAT, сохраните у строки `source_id`, `source_task_id`, `source_frame_id` (и, если оставили, `source_project_id`) из выгрузки. Без них ошибка считается не связанной с кадром (`unmapped_errors`);
- чтобы работали решения о пересечении, сохраните `source_id`.

### Как это работает

1. Читает запись датасета, загружает реестр классов с `api_url` и ищет последнюю версию в ClearML. Без `--first` она должна быть управляемой (с блоком `managed` в `dataset.yaml`) и становится родительским датасетом. С `--first` она не должна быть управляемой, и из неё ничего не берётся. Если версий нет, подготовка делает первую версию с флагом и без него.
2. Сверяет снимок источников из `--source` с текущим описанием источников и с последней версией в ClearML: отличия описания только печатаются предупреждениями, новая версия в ClearML останавливает подготовку (см. «[Что останавливает команды и что только предупреждает](#что-останавливает-команды-и-что-только-предупреждает)»).
3. Строит список классов: номера и имена из реестра, отметки исключённых классов из `empty_classes`.
4. Проверяет, что изображения лежат в разрешённых локальных корнях и корнях `s3_roots`, и что каждый корень `s3_roots` доступен.
5. Считает SHA-256 каждого изображения и применяет решения о пересечении.
6. Переносит опубликованный split (см. ниже) в столбец `split`.
7. Проверяет строки и изображения по профилю `clearml-yolo`. Пустой `split` при этом разрешён: такие изображения попадают в `pending`.
8. Проверяет блокирующие условия ([blocker](../../GLOSSARY.md)). Подготовка готова, если их нет:

   | Условие | Строка в `blockers` |
   |---|---|
   | Структурные ошибки CSV или не осталось ни одного годного изображения | `Input CSV has structural validation errors.`, `No valid images remain for upload.` |
   | Нужна очистка, а передан `--no-clean` | `Cleanup is needed and --no-clean was given.` |
   | У класса, который не исключён, нет ни одного bbox ни в одном split | `Active classes have no bbox: <классы>` |
   | Одно и то же изображение (по SHA-256 содержимого, под одним или разными именами) стоит в нескольких split | `Image content has rows in several splits: <имена>` |

   Строки, которые убирает очистка, сами по себе подготовку не блокируют. Класс без bbox исключите (`empty_classes` в записи датасета) или добавьте его разметку.

   Условия split, которые потребует `publish`, но которые пока не выполнены, попадают в `pending`. Если у каких-то изображений пустой `split`, там одна строка `заполните split у <N> изображений в <каталог>/dataset.csv`. Если split заполнен у всех строк, там пустые `train` или `val` и отсутствие bbox в `train`: `в train нет изображений`, `в val нет изображений`, `в train нет ни одного bbox`. Условия `pending` подготовку не блокируют.
9. Собирает замечания к кадрам: ошибки в строках, которые указывают на кадр задачи из снимка источников.
10. Пишет каталог подготовки. Сначала всё пишется во временный каталог рядом, затем переносится.

#### Откуда берётся split

Split — ваш: cveta2 никогда не назначает его сам. Он только сохраняет опубликованный split изображения, которое уже опубликовано в родительской версии. В первой версии (новый датасет или `--first`) родителя нет, поэтому все изображения новые и весь split берётся из вашего CSV.

Изображение, опубликованное в родительской версии, получает опубликованный split ([stable split](../../GLOSSARY.md)). Изображение узнаётся по SHA-256 содержимого, поэтому порядок строк и имена файлов не влияют. Значение из вашего CSV заменяется; число заменённых строк — `split_replacements` в `report.json`.

Изображение, удалённое из датасета, сохраняет запись о своём split: если оно вернётся, оно попадёт в тот же split.

Новое изображение сохраняет split из вашего CSV. Пустой split не блокирует подготовку: изображение попадает в `pending` (`заполните split у <N> изображений в <каталог>/dataset.csv`), а `dataset.csv` записывается с пустым split. Заполните его в `<каталог>/dataset.csv` подготовки или в преобразованном CSV перед новым `prepare`. Split, не равный `train`, `val` или `test`, — ошибка строки: очистка удаляет строки этого изображения. Если у другой строки того же изображения стоит другой split, это одно изображение в нескольких split: подготовка блокируется (см. ниже), а не очищается.

Одно изображение (по SHA-256 содержимого) может стоять только в одном split. Если его строки — под одним именем или под разными — стоят в разных split, подготовка блокируется: `Image content has rows in several splits: <имена>`. Очистка такие строки не удаляет молча: исправьте split в CSV.

Ошибки split не отправляются в CVAT как замечания: их исправляет автор преобразованного CSV, а не разметчик. Это касается и остальных строк изображения, которые отклонены только из-за ошибки split.

#### Решения о пересечении

Если одно и то же изображение (по SHA-256 содержимого) пришло из нескольких источников, нужно решение в `overlaps`. Без него `prepare` останавливается с ошибкой, в которой есть SHA-256 и список источников — их можно скопировать в конфигурацию. При решении с `source` остаются только строки этого источника; при `source: null` изображение удаляется. Если состав источников изменился, решение нужно пересмотреть.

### Результат

Каталог подготовки:

| Файл | Когда | Что это |
|---|---|---|
| `transformed.csv` | всегда | Копия вашего CSV. |
| `source-snapshot.yaml` | всегда | Копия снимка источников из `--source`. |
| `report.json` | всегда | Отчёт проверки ([verification report](../../GLOSSARY.md)). |
| `broken-images.csv` | всегда | Отклонённые строки. |
| `dataset.csv`, `dataset.yaml`, `tasks.yaml` | только если нет блокирующих условий | Данные для публикации. |
| `preparation.json` | всегда | Запись подготовки: имя датасета, родительский датасет, замечания к кадрам, `ready`, `clean`. Контрольных сумм нет. |

Содержимое файлов описано в [dataset-format.md](../dataset-format.md#dataset-prepare). Файлы можно править после подготовки: `report-errors` и `publish` читают их такими, какие они сейчас. Что `publish` сохраняет, а что пересчитывает, — в «[Что можно править](#что-можно-править)».

Вывод (сокращён):

```json
{
  "directory": "output/prepared",
  "ready": true,
  "report": {
    "profile": "clearml-yolo",
    "is_valid": false,
    "requires_cleanup": true,
    "structural_errors": false,
    "counts": {"input_rows": 12, "clean_rows": 11, "broken_rows": 1, "input_images": 12, "clean_images": 11},
    "issues": [
      {"code": "invalid_box_area", "severity": "error", "row_position": 0, "message": "Box width and height must each exceed 2 px; ..."}
    ],
    "ready": true,
    "blockers": [],
    "broken_image_rows": 1,
    "mapped_findings": 1,
    "unmapped_errors": 0,
    "split_replacements": 12,
    "pending": ["заполните split у 3 изображений в output/prepared/dataset.csv"],
    "missing_classes": [],
    "split_collisions": []
  }
}
```

`mapped_findings` — сколько замечаний к кадрам будет отправлено в CVAT, `unmapped_errors` — сколько строк с ошибками не удалось связать с кадром, `split_replacements` — у скольких строк cveta2 изменил значение `split`, `pending` — условия split, которые потребует `publish`, но которые пока не выполнены, `missing_classes` — классы без bbox, `split_collisions` — имена изображений, у содержимого которых строки в нескольких split.

Код завершения `0` — готово (условия `pending` могут оставаться), `1` — каталог записан, но есть блокирующие условия (например, нужна очистка, а передан `--no-clean`), `2` — ошибка, каталог не создан.

### Что останавливает команды и что только предупреждает

`prepare`, `report-errors` и `publish` работают с текущими файлами и текущей конфигурацией. Команду останавливают только эти случаи:

| Что случилось | Какие команды | Сообщение | Что делать |
|---|---|---|---|
| В ClearML появилась новая версия датасета: после `fetch` (для `prepare`) или после `prepare` (для `report-errors` и `publish`) | все три | `Source parent changed; fetch the managed dataset again`, `Latest ClearML parent changed; fetch and prepare again`, `ClearML parent version changed; prepare again` | новый `fetch`, затем `prepare` |
| Адрес или организация CVAT в общей конфигурации не те, с которых `fetch` выгрузил задачи | `report-errors`, `publish` | `CVAT server differs from the one fetched: fetched <адрес> (organization <организация>), configured <адрес> (organization <организация>); fetch the managed dataset again` | новый `fetch`, затем `prepare` |
| Задача CVAT завершена сейчас, а `fetch` не записал её завершённой | `report-errors`, `publish` | `CVAT tasks completed after fetch: <источник>/<задача>, …; fetch the managed dataset again` | новый `fetch`, затем `prepare` |
| Имена или номера классов в `dataset.yaml` подготовки расходятся с реестром классов, или строки не проходят другое правило содержимого или split | `publish` (реестр классов, правила split), `prepare` и `publish` (правила содержимого) | `Class names or numbers differ from the class registry: <имена>; prepare again`; блокирующие проблемы в `report.json`; `Prepared dataset.csv does not pass validation: …` и другие сообщения из «[Что останавливает публикацию](#что-останавливает-публикацию)» | исправьте данные или подготовьте заново |

Остальное только предупреждает: команда печатает `<отличие>. Датасет собирается из выгруженных данных.` и продолжает с данными из `fetch`. Замечания к кадрам задач с предупреждением не отправляются.

| Предупреждение | Какие команды | Когда |
|---|---|---|
| `Источник отличается от выгруженного: <источник>: <поле> <было> → <стало>` | все три | У источника в общей конфигурации другой тип, ID проекта CVAT или `uri`, чем в снимке источников. |
| `Источник отличается от выгруженного: <источник>: только в снимке` или `только в описании` | все три | Источник убрали из записи датасета или добавили в неё после `fetch`. |
| Изменения задач и меток проектов CVAT, объектов S3 | `report-errors`, `publish` | Задачу изменили, переоткрыли, удалили или добавили в список игнорируемых после `fetch`; появилась незавершённая задача; изменились метки проекта; в S3 лежит другой объект. Полный список — в [Изменения источников после fetch](#изменения-источников-после-fetch). |

Остальные ключи записи датасета (`api_url`, `s3_roots`, `empty_classes`, `overlaps`) и поля реестра классов, кроме имени и номера (порог, флаги), с подготовкой не сравниваются: `report-errors` и `publish` берут их из файлов подготовки, а новые значения применит следующий `prepare`. Ключ `clearml` команды берут из текущей конфигурации: если его изменить, они ищут родительский датасет уже в новом месте и останавливаются с `Latest ClearML parent changed; fetch and prepare again`. Адрес и организацию CVAT `prepare` не проверяет, а `report-errors` и `publish` у датасета хотя бы с одним источником CVAT сравнивают с теми, что записал `fetch`, и при отличии останавливаются: ID задач из снимка относятся к другому серверу, поэтому проверить их свежесть нельзя, а замечания могли бы попасть в чужие задачи. Адрес сравнивается без завершающего `/`, пустая организация равна её отсутствию.

Кроме того, `report-errors` и `publish` проверяют, что каталог подготовки читается, а `publish` — ещё текущие `dataset.csv` и `dataset.yaml`, изображения и корни изображений (см. их «Частые ошибки»). Контрольных сумм нет: правки файлов подготовки разрешены, если результат проходит проверки.

### Частые ошибки

| Сообщение | Причина и решение |
|---|---|
| `Preparation directory already exists: <каталог>` | Каталог `--output-dir` уже есть. Укажите новый. |
| `Preparation must be outside the fetch source directory: <каталог>` | Каталог подготовки внутри каталога выгрузки. Выберите другой. |
| `Expected a regular nonsymlink file: <файл>` | CSV или `source-snapshot.yaml` не найден, это каталог или символическая ссылка. |
| `Transformed images are outside approved roots: [...]` | Пути `image_path` вне разрешённых локальных корней. Положите изображения в кэш изображений или поправьте пути. |
| `S3 image path is outside approved S3 roots: ...` | Значение `s3_image_path` не попадает ни в один корень `s3_roots`. |
| `Image overlap requires source selection or exclusion: <sha256>; sources=[...]` | Изображение пришло из нескольких источников. Добавьте решение в `overlaps`. |
| `Image overlap membership changed; review decision: <sha256>` | Список `members` не совпадает с фактическими источниками. |
| `Conflicting image filename for different content: <имя>` | Одно `image_name` у разных изображений. Переименуйте одно из них. |
| `Shared exclusion policy contains unknown class identities` | В `empty_classes` номер, которого нет в реестре классов. |
| `Parent <id> is not a managed dataset version; start a managed lineage with dataset prepare --first` | Последняя версия в ClearML сделана не через `dataset publish`: в её `dataset.yaml` нет блока `managed` или самого `dataset.yaml` нет. Подготовьте первую управляемую версию с `--first`. |
| `Managed lineage already exists at parent <id>; prepare without --first` | Последняя версия уже управляемая, а передан `--first`. Уберите флаг: подготовка продолжит историю от этой версии. |
| `Invalid dataset metadata <путь>/dataset.yaml: <поле>: ...` | `dataset.yaml` последней версии в ClearML не читается как метаданные датасета. Без `--first` подготовка останавливается. Если это версия, сделанная не через `dataset publish`, начните управляемую историю с `--first`. |
| `Source parent changed; fetch the managed dataset again` | После `fetch` в ClearML появилась новая версия датасета. Сделайте новый `fetch` и `prepare`. |
| `Source snapshot lacks the CVAT server identity; fetch and prepare again` | В `source-snapshot.yaml` с источниками CVAT нет адреса CVAT: выгрузка сделана старой версией cveta2. Сделайте новый `fetch` и `prepare`. |

### Из Python

```python
cveta2.prepare_managed_dataset(
    name: str,
    csv: Path,
    *,
    source: Path,
    output_dir: Path,
    clean: bool = True,
    first: bool = False,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> PreparationSummary
```

`clean=False` — то же, что флаг `--no-clean`. `first=True` — то же, что флаг `--first`.

Возвращает объект с полями `directory`, `ready` и `report` (словарь из `report.json`). Неготовая подготовка — это не исключение: проверяйте `ready`. Ошибки — исключения `cveta2.Cveta2Error`.

```python
from pathlib import Path
import cveta2

summary = cveta2.prepare_managed_dataset(
    "shelves-det",
    Path("output/transformed.csv"),
    source=Path("output/fetch"),
    output_dir=Path("output/prepared"),
)
print(summary.ready, summary.report["counts"], summary.report["pending"])
```

## diff

Сравнивает два датасета: локальные CSV, каталоги или опубликованные версии ClearML. Ничего не меняет.

### Синтаксис и аргументы

```text
cveta2 dataset diff [--config CONFIG] [--global-config GLOBAL_CONFIG] [--json] old new
```

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `old` | обязателен | Старый датасет: CSV-файл, каталог с `dataset.csv` или ID версии в ClearML. |
| `new` | обязателен | Новый датасет, в тех же форматах. |

### Как это работает

1. Для каждого аргумента: если это каталог, берётся его `dataset.csv`; если это файл, берётся он сам; иначе аргумент считается ID версии ClearML и `dataset.csv` скачивается оттуда.
2. Строки сравниваются как мультимножества по всем столбцам; порядок столбцов и строк не важен.
3. Изображения группируются по `image_name` (если столбца нет — по `image_path`). Изображение «изменено», если его набор строк стал другим.
4. Классы — непустые значения `instance_label`. Split считается по уникальным изображениям.

Каталог выгрузки, каталог подготовки и опубликованная версия сравниваются одинаково — по их `dataset.csv`.

### Результат

```json
{
  "rows": {"old": 11, "new": 12, "added": 2, "removed": 1, "unchanged": 10},
  "images": {"added": ["shelf_0025.jpg"], "removed": [], "changed": ["extra-3.png"]},
  "classes": {"added": ["dog"], "removed": []},
  "splits": {"old": {"test": 1, "train": 9, "val": 1}, "new": {"test": 1, "train": 9, "val": 2}}
}
```

### Частые ошибки

| Сообщение | Причина и решение |
|---|---|
| `Cannot read published managed dataset; check ClearML configuration, credentials and connectivity (Task ID "<аргумент>" could not be found)` | Аргумент не файл и не каталог, и в ClearML нет версии с таким ID. Проверьте путь или ID. |
| `Managed CSV must have unique, nonempty string columns` | В CSV повторяются или пустые имена столбцов. |

### Из Python

```python
cveta2.compare_datasets(
    old: str, new: str, *, config_path: Path | None = None, project_config: Path | None = None
) -> dict[str, Any]
```

```python
import cveta2

result = cveta2.compare_datasets("output/prepared-v1", "output/prepared-v2")
print(result["rows"], result["classes"])
```

## report-errors

Отправляет в CVAT замечания к кадрам из подготовки: по одному issue на кадр с ошибками. Работает и с неготовой подготовкой — так разметчики могут исправить ошибки до публикации.

### Синтаксис и аргументы

```text
cveta2 dataset report-errors [--config CONFIG] [--global-config GLOBAL_CONFIG] [--json] prepared
```

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `prepared` | обязателен | Каталог, созданный `dataset prepare`. |

### Как это работает

1. Читает текущие файлы каталога; контрольных сумм нет.
2. Выполняет те же проверки свежести, что и `publish` (см. ниже): родительский датасет и источники. Файлы данных, изображения и классы не проверяются, поэтому команда работает и с подготовкой, которую `prepare` заблокировал. Из изменений источников команду останавливает только задача CVAT, завершённая после `fetch`; отличия описания источников от снимка и остальные изменения источников печатаются предупреждениями ([Изменения источников после fetch](#изменения-источников-после-fetch)).
3. Для каждого замечания к кадру, кроме замечаний к задачам с предупреждением (они пропускаются и считаются в `skipped`):
   1. Ищет на этом кадре задачи issue с меткой этого замечания. Если есть — замечание считается уже доставленным.
   2. Иначе записывает запись о доставке замечания ([feedback receipt](../../GLOSSARY.md)), создаёт issue и проверяет, что аннотации задачи за это время не менялись и issue появился. Затем отмечает запись как доставленную.

Что создаётся в CVAT: issue на этом кадре в единственном job типа annotation, который содержит кадр, в точке (0, 0). Текст issue:

```text
[cveta2:verification:<метка>]
cveta2 dataset verification: <коды ошибок через запятую>
<сообщения об ошибках, по одному на строку>
```

Метка — SHA-256 от источника, проекта, задачи, кадра и кодов ошибок. Поэтому повторный запуск, а также другая подготовка с теми же ошибками на том же кадре не создают второй issue. cveta2 только создаёт issue; аннотации, метки и stage/state job он не меняет.

Записи о доставке хранятся в каталоге `managed-feedback/` рядом с файлом личной конфигурации, в файле `<SHA-256 source-snapshot.yaml>.json`. Этот файл общий для всех подготовок из одной выгрузки. Если запуск прервался между записью и созданием issue, следующий запуск по этому файлу узнаёт свой issue и не создаёт его снова.

Замечания создаются только для строк с ошибками (severity `error`), у которых `source_id`, `source_task_id`, `source_frame_id` указывают на кадр задачи CVAT из снимка источников. Строки из `s3-csv` и строки без этих столбцов попадают в `unmapped` и в CVAT не отправляются.

### Результат

```json
{
  "created": 1,
  "existing": 0,
  "unmapped": 0,
  "failed": [],
  "skipped": 0
}
```

| Поле | Значение |
|---|---|
| `created` | Сколько issue создано сейчас. |
| `existing` | Сколько замечаний уже были в CVAT. |
| `unmapped` | Сколько строк с ошибками не связано с кадром CVAT. |
| `failed` | Недоставленные замечания: `<источник>/<задача>/<кадр>: <причина>`. |
| `skipped` | Сколько замечаний не отправлено, потому что их задача изменилась после `fetch` (в том числе уже доставленные раньше). |

Код завершения `0`, если `failed` пуст; `2`, если хотя бы одно замечание не доставлено (JSON всё равно печатается) или проверка свежести не прошла.

### Частые ошибки

| Сообщение | Причина и решение |
|---|---|
| `Cannot load managed preparation: <каталог>: <поле>: <ошибка>` | Файл каталога подготовки не разбирается, или в `preparation.json` другой `format_version`. Сообщение называет поле, но не его значение. Исправьте файл или подготовьте заново. |
| `Source annotations changed during feedback: <задача>` (в `failed`) | Задачу меняли во время отправки. Сделайте новый `fetch` и `prepare`. |
| `Feedback frame has no unique annotation job` (в `failed`) | Кадр не входит ровно в один job типа annotation. |
| `CVAT tasks completed after fetch: <источник>/<задача>, …; fetch the managed dataset again` | После `fetch` задачи завершили: их принятой разметки нет в выгрузке. Сделайте новый `fetch` и `prepare`. |
| `Cannot read required S3 CSV source: s3://...` | Метаданные объекта S3 CSV-источника не читаются: объект удалён или нет доступа. |
| `CVAT server differs from the one fetched: fetched …, configured …; fetch the managed dataset again` | В общей конфигурации другой адрес или организация CVAT, чем при `fetch`. Верните прежние или сделайте новый `fetch` и `prepare`. |

### Из Python

```python
cveta2.report_dataset_errors(
    prepared: Path, *, config_path: Path | None = None, project_config: Path | None = None
) -> FeedbackOutcome
```

Возвращает объект с полями `created`, `existing`, `unmapped`, `failed`, `skipped`. Ошибка доставки отдельного замечания не бросает исключение, а попадает в `failed`; ошибки проверок — исключение `cveta2.Cveta2Error`.

```python
from pathlib import Path
import cveta2

outcome = cveta2.report_dataset_errors(Path("output/prepared"))
print(outcome.created, outcome.existing, outcome.failed, outcome.skipped)
```

## publish

Публикация ([publication](../../GLOSSARY.md)): перепроверяет готовую подготовку, доставляет замечания в CVAT и загружает три файла новой финализированной версией в ClearML.

### Синтаксис и аргументы

```text
cveta2 dataset publish [--config CONFIG] [--global-config GLOBAL_CONFIG] [--json] [--force-resplit] prepared
```

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `prepared` | обязателен | Готовый каталог, созданный `dataset prepare`. |
| `--force-resplit` | выключен | Разрешить split, отличный от опубликованного в родительской версии; опубликованные назначения заменятся значениями из `dataset.csv`. Одно изображение в нескольких split флаг не разрешает. |

### Как это работает

1. Читает текущие файлы каталога; контрольных сумм нет. Если `prepare` был заблокирован и не записал `dataset.csv`, `dataset.yaml` и `tasks.yaml`, публикация останавливается.
2. Проверяет свежесть:
   - описание источников в общей конфигурации сравнивается со снимком источников; отличия только печатаются предупреждениями `Источник отличается от выгруженного: …`;
   - последняя версия в ClearML — та же, что при подготовке, с той же версией, и у неё есть `dataset.yaml` (для подготовки с `--first` `dataset.yaml` не нужен);
   - у датасета с источниками CVAT адрес и организация CVAT те же, что записал `fetch`;
   - нет задач CVAT, завершённых после `fetch`; остальные изменения задач, меток проектов и объектов S3 только печатаются предупреждениями ([Изменения источников после fetch](#изменения-источников-после-fetch)).
3. Копирует `dataset.csv`, `dataset.yaml` и `tasks.yaml` во временный каталог. Все следующие проверки идут по этой копии, и публикуется она же: правка файлов подготовки, сделанная во время публикации, в версию не попадёт.
4. Проверяет текущие строки и `dataset.yaml`, по порядку:
   1. имена и номера классов совпадают с реестром классов с `api_url` из `dataset.yaml`; остальные поля реестра (порог, флаги) не сравниваются;
   2. корни изображений из `dataset.yaml` покрывают пути изображений, локальные корни существуют, корни `s3_roots` доступны; изображения читаются только после этой проверки;
   3. ни одно изображение (по SHA-256 содержимого) не стоит в нескольких split;
   4. у каждой строки заполнен split;
   5. строки с текущими изображениями проходят проверку `clearml-yolo` без очистки;
   6. в `train` и `val` есть изображения, а в `train` — хотя бы один bbox;
   7. у каждого класса, который не отмечен `empty: true`, есть хотя бы один bbox;
   8. изображения, опубликованные в родительской версии, сохранили опубликованный split (без `--force-resplit`).
5. Пересчитывает служебные данные из текущих строк и пишет их и в копию, и в каталог подготовки (см. «[Что можно править](#что-можно-править)»).
6. Доставляет замечания к кадрам так же, как `report-errors`, кроме замечаний к задачам с предупреждением: они пропускаются, и команда печатает их число. Если хотя бы одно замечание не доставлено, публикация останавливается.
7. Ещё раз проверяет источники и родительский датасет: задача CVAT, завершённая за это время, останавливает публикацию; предупреждения второй раз не печатаются. Изменения задач, вызванные только своими issue из записей о доставке, не считаются изменением.
8. Создаёт в ClearML новый датасет в `clearml.project` с именем `clearml.dataset`, дочерний к родительскому, загружает в него три файла копии и финализирует. Если в записи датасета задан `clearml.output_uri`, файлы загружаются туда. Номер версии назначает ClearML. Подготовка с `--first` публикуется без родителя, даже если в ClearML есть более ранние версии без управляемых метаданных.

#### Что можно править

После `prepare` и до `publish` файлы подготовки можно править; `publish` проверит то, что в них сейчас.

- Сохраняются как есть: строки `dataset.csv`, отметки `empty` классов, `api_url` и корни изображений (`images.local_root`, `images.s3_root`) в `dataset.yaml`.
- Пересчитываются из текущих строк и общей конфигурации: блок `managed` в `dataset.yaml` (назначения split, копия записи датасета, её хеш) и весь `tasks.yaml` (списки задач, назначения split, SHA-256 изображений, хеши записи датасета, реестра классов и меток). Ручные правки там перезаписываются и в опубликованной версии, и в каталоге подготовки.
- Отметка `empty: true`, поставленная вручную, действует только в этой публикации. Следующий `prepare` снова берёт отметки из `empty_classes` записи датасета: чтобы класс оставался исключённым, добавьте его туда.
- `source-snapshot.yaml` — записанные данные `fetch`, их не правят. Правка меняет SHA-256 файла, по которому находится общий файл записей о доставке: записи прежних отправок теряются. Изменённые задачи и метки считаются изменившимися после `fetch`, и их замечания пропускаются; без записей реестра классов или меток команда останавливается. Пересчитанные хеши в `tasks.yaml` строятся из этого файла, поэтому правка попадёт и в опубликованную версию. Вместо правки сделайте новый `fetch` и `prepare`.

#### Правила split

- Опубликованное изображение сохраняет свой split ([stable split](../../GLOSSARY.md)): его ищут по SHA-256 содержимого в назначениях `managed.assignments` родительской версии. Если в `dataset.csv` у него другой split, публикация останавливается и называет до 20 таких изображений с опубликованным и текущим split. С `--force-resplit` значение из `dataset.csv` заменяет опубликованное назначение, и следующие версии берут уже его. В подготовке с `--first` родителя нет, и правило не применяется.
- Одно изображение — один split, всегда: строки одного содержимого (под одним именем или под разными) в разных split останавливают публикацию и с `--force-resplit`.
- Изображение, убранное из `dataset.csv`, сохраняет своё назначение: если оно вернётся в следующей версии, оно попадёт в прежний split.
- Split, заполненный в `<каталог>/dataset.csv` после `prepare` (например, изображения из `pending`), записывается в назначения и сохраняется в следующих версиях.

#### Что останавливает публикацию

- заблокированная подготовка без `dataset.csv`, `dataset.yaml`, `tasks.yaml`;
- новая версия в ClearML после подготовки, другой адрес или организация CVAT, задача CVAT, завершённая после `fetch` (см. «[Что останавливает команды и что только предупреждает](#что-останавливает-команды-и-что-только-предупреждает)»);
- каждая проверка шага 4: реестр классов, корни, одно изображение в нескольких split, пустой split, отклонённые строки или нужные исправления, пустые `train` или `val` и отсутствие bbox в `train`, класс без bbox, изменённый split опубликованного изображения;
- недоставленное замечание к кадру;
- новая версия в ClearML, появившаяся во время доставки замечаний.

Остальные изменения источников только предупреждают: [Изменения источников после fetch](#изменения-источников-после-fetch). Сообщения — в «[Частые ошибки](#частые-ошибки-4)».

#### Изменения источников после fetch

`report-errors` и `publish` сравнивают источники с тем, что записал `fetch` в снимок источников. Читаются только списки задач, метки проектов и метаданные объектов S3; аннотации и содержимое CSV не скачиваются. Задачи из текущего списка игнорируемых не проверяются; если задачу из снимка добавили в этот список после `fetch`, команда предупреждает об этом. Кроме того, описание источников в общей конфигурации сравнивается со снимком: тип, ID проекта CVAT и `uri` каждого источника.

Данные и источники останавливают команду в четырёх случаях:

- у датасета с источниками CVAT адрес или организация CVAT в общей конфигурации не те, что записал `fetch`: `CVAT server differs from the one fetched: …; fetch the managed dataset again`. Сделайте новый `fetch` и `prepare`;
- для `publish`: текущие строки `dataset.csv` не проходят проверки содержимого и split или имена и номера классов расходятся с реестром классов (см. «[Что останавливает публикацию](#что-останавливает-публикацию)»);
- в ClearML появилась новая версия датасета;
- задача CVAT завершена сейчас (все job на stage `acceptance` в state `completed`), а `fetch` не записал её завершённой: она новая или её доделали после `fetch`. Её принятой разметки нет в выгрузке, поэтому команда завершается с `CVAT tasks completed after fetch: <источник>/<задача>, …; fetch the managed dataset again`. Сделайте новый `fetch` и `prepare`.

Остальные отличия только предупреждают. Для каждого команда печатает строку `<отличие>. Датасет собирается из выгруженных данных.` и продолжает с данными из `fetch`:

| Отличие | Когда | Замечания к кадрам |
|---|---|---|
| `Источник отличается от выгруженного: <источник>: <поле> <было> → <стало>` | У источника в общей конфигурации другой тип, ID проекта CVAT или `uri`, чем в снимке. | не отправляются для всех задач источника |
| `Источник отличается от выгруженного: <источник>: только в снимке` или `только в описании` | Источник убрали из записи датасета или добавили в неё после `fetch`. | не отправляются для всех задач источника из снимка |
| `<источник>: новая незавершённая задача <id>` | В проекте появилась задача, которая ещё не завершена. | — |
| `<источник>: задача <id> удалена` | Задачи из снимка больше нет в проекте. | не отправляются |
| `<источник>: задача <id> теперь игнорируется` | Задачу из снимка добавили в список игнорируемых после `fetch`. | не отправляются |
| `<источник>: задача <id> переоткрыта` | Задача была завершена при `fetch`, а сейчас нет. | не отправляются |
| `<источник>: задача <id> изменена после fetch` | У задачи другое время изменения. | не отправляются |
| `<источник>: изменились метки проекта` | Изменились определения меток проекта. | не отправляются для всех задач источника |
| `<источник>: проект <id> больше не описан в конфигурации, задачи не проверены` | Проекта источника нет в разделе `projects` общей конфигурации. | не отправляются для всех задач источника |
| `<источник>: в S3 лежит другой объект (ETag или версия)` | У CSV-объекта другой ETag или ID версии; содержимое не сравнивается. | — |
| `<источник>: в снимке нет ETag и версии, проверить объект нельзя` | S3 не вернул ни ETag, ни версию при `fetch`. | — |

Замечания к задачам с предупреждением не отправляются, потому что их кадры могли измениться; уже доставленные раньше тоже считаются пропущенными. Команда печатает `Замечаний не отправлено: <n>: их задачи изменились после fetch`, `report-errors` возвращает это число в `skipped`. Чтобы отправить их, сделайте новый `fetch` и `prepare`.

Если прошлая отправка замечания прервалась, а его задачи в CVAT больше нет (удалена, перенесена в другой проект или недоступна вашей учётной записи), команда печатает `<источник>: задача <id> недоступна в CVAT (<причина>); незавершённая отправка замечания осталась незавершённой`, оставляет запись о доставке как есть и пропускает замечания этой задачи. Если CVAT не отвечает или отказывает в доступе к самому проекту, команда завершается с ошибкой: проверить свежесть источников нельзя. Так же команда завершается с `Cannot read required S3 CSV source: s3://...`, если метаданные объекта S3 CSV-источника не читаются (объект удалён или нет доступа).

### Результат

```json
{
  "dataset_id": "7f6e5d4c3b2a41908f7e6d5c4b3a2910",
  "version": "1.0.1"
}
```

Кроме JSON, ClearML SDK печатает ссылку на страницу датасета и ход загрузки.

После публикации подготовки этого датасета, сделанные до неё, опубликовать уже нельзя: родительский датасет изменился. Следующий цикл начинается с нового `fetch`.

### Частые ошибки

| Сообщение | Причина и решение |
|---|---|
| `Preparation was blocked and has no payload; see report.json and prepare again` | `prepare` был заблокирован и не записал `dataset.csv`, `dataset.yaml` и `tasks.yaml`. Посмотрите `blockers` в `report.json`, исправьте данные и подготовьте заново (без `--no-clean`, если блокирует очистка). |
| `Prepared dataset.csv does not pass validation: <n> rejected rows, repairs needed: <yes/no>`, ниже по строке на проблему: блокирующие проблемы, затем `row <номер>: <ошибка>` | Текущие строки `dataset.csv` с текущими изображениями не проходят проверку `clearml-yolo`: строки отклонены, нужны исправления (например, обрезка рамок) или есть блокирующие проблемы. Называются первые 20 проблем, затем `and <N> more`; номер строки считается от 0, без строки заголовка, как в `verify`. Строка класса, отмеченного `empty: true`, — тоже отклонённая строка. Split, не равный `train`, `val` или `test`, — тоже отклонённая строка. Исправьте `dataset.csv` или изображения либо подготовьте заново. |
| `Prepared dataset.csv is not ready for publication: заполните split у <N> изображений в <каталог>/dataset.csv` | У строк этих изображений пустой split — те же слова, что в `pending` после `prepare`. Заполните split в `dataset.csv` подготовки. |
| `Prepared dataset.csv is not ready for publication: в train нет изображений`, `в val нет изображений`, `в train нет ни одного bbox` | Split заполнен у всех строк, но для обучения не хватает `train`, `val` или bbox в `train`. Перенесите изображения или добавьте строки. |
| `Image content has rows in several splits: <имена>; one image may have one split` | Строки одного изображения (по SHA-256 содержимого, под одним именем или под разными) стоят в разных split. `--force-resplit` этого не разрешает: оставьте изображению один split. |
| `Images published in the parent must keep their split: <изображение> (<было> → <стало>), …; restore the split in dataset.csv or pass --force-resplit` | У изображений, опубликованных в родительской версии, в `dataset.csv` другой split. У каждого изображения названы опубликованный и текущий split. Называются первые 20 изображений, затем `and <N> more`. Верните опубликованный split или запустите с `--force-resplit`, чтобы заменить назначение. |
| `Active classes have no bbox: <классы>; mark them empty: true in dataset.yaml or add rows with them` | У класса, не отмеченного `empty: true`, нет ни одного bbox. Отметьте его `empty: true` в `dataset.yaml` подготовки (для следующих подготовок — в `empty_classes`) или добавьте строки с ним. |
| `Cannot load managed preparation: <каталог>: <поле>: <ошибка>` | Файл каталога подготовки не разбирается, или в `preparation.json` другой `format_version`. Сообщение называет поле, но не его значение. Исправьте файл или подготовьте заново. |
| `Invalid dataset metadata <путь>/dataset.yaml: <поле>: <ошибка>` | `dataset.yaml` родительской версии не читается как метаданные датасета. Сообщение называет поле, но не его значение. |
| `Latest ClearML parent changed; fetch and prepare again` | После подготовки в ClearML опубликована другая версия; для подготовки с `--first` — тоже любая новая версия, управляемая или нет. Сделайте новый `fetch` и `prepare`. |
| `Parent <id> lacks dataset.yaml and is no longer a managed dataset version; fetch and prepare again, with dataset prepare --first to start a managed lineage` | У родительской версии пропал `dataset.yaml`, и она больше не управляемая. Сделайте новый `fetch` и `prepare` с `--first`. |
| `Class names or numbers differ from the class registry: <имена>; prepare again` | Имена или номера классов в `dataset.yaml` подготовки расходятся с реестром классов: класс переименовали, перенумеровали, добавили или убрали. Подготовьте заново. |
| `Cannot read required S3 CSV source: s3://...` | Метаданные объекта S3 CSV-источника не читаются: объект удалён или нет доступа. |
| `CVAT server differs from the one fetched: fetched …, configured …; fetch the managed dataset again` | В общей конфигурации другой адрес или организация CVAT, чем при `fetch`. Верните прежние или сделайте новый `fetch` и `prepare`. |
| `CVAT tasks completed after fetch: <источник>/<задача>, …; fetch the managed dataset again` | После `fetch` задачи завершили: их принятой разметки нет в выгрузке. Сделайте новый `fetch` и `prepare`. |
| `CVAT feedback delivery failed; retry report-errors before publication` | Замечание не доставлено. Запустите `report-errors`, посмотрите `failed`. |
| `ClearML parent changed during feedback; prepare again` | Пока доставлялись замечания, в ClearML появилась новая версия. Сделайте новый `fetch` и `prepare`. |

### Из Python

```python
cveta2.publish_dataset(
    prepared: Path,
    *,
    force_resplit: bool = False,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> Publication
```

`force_resplit=True` — то же, что флаг `--force-resplit`. Возвращает `cveta2.Publication` с полями `dataset_id` и `version`. Ошибки — исключение `cveta2.Cveta2Error`.

```python
from pathlib import Path
import cveta2

publication = cveta2.publish_dataset(Path("output/prepared"))
print(publication.dataset_id, publication.version)
```

Подключение к CVAT, S3 и ClearML и общие исключения описаны в [python-api.md](../python-api.md).

## См. также

- [configuration.md](../configuration.md) — личная и общая конфигурация, разделы `projects` и `datasets`.
- [dataset-format.md](../dataset-format.md) — столбцы CSV и файлы подготовленного датасета.
- [images-and-cache.md](../images-and-cache.md) — кэш изображений и его каталоги.
- [verify](verify.md) и [upload-dataset](upload-dataset.md) — подготовка каталога и публикация без управляемого датасета.
- [ignore](ignore.md) — список игнорируемых задач.
- [workflows.md](../workflows.md) — сценарии целиком.

# cveta2 upload-dataset

Публикует подготовленный датасет ([prepared bundle](../../GLOSSARY.md)), созданный командой [`verify --bundle`](verify.md#ручная-подготовка---bundle), как новую завершённую версию датасета в ClearML. Команда проверяет файлы каталога такими, какие они сейчас: после `verify` их можно править, и публикуется то, что проходит проверки ([publication](../../GLOSSARY.md)).

> **Внимание.** Опубликованную версию команда не удаляет и не заменяет. Новая публикация с тем же именем создаёт следующую версию, а не исправляет прежнюю.

## Примеры

Опубликовать подготовленный каталог:

```bash
cveta2 upload-dataset output/prepared-1
```

Полный цикл: подготовить, просмотреть и поправить файлы, опубликовать:

```bash
cveta2 verify ~/data/fetch --bundle --project "Retail/Datasets" --dataset-name retail-shelves \
  --api-url https://classes.example.com/api --local-root ~/data/images \
  --accept-default-classes --clean --output-dir output/prepared-1 --non-interactive
less output/prepared-1/report.json
cveta2 upload-dataset output/prepared-1
```

Опубликовать, хотя изображения, уже опубликованные в родителе, теперь в другом split:

```bash
cveta2 upload-dataset output/prepared-1 --force-resplit
```

Если в `dataset.csv` заполнен `s3_image_path`, добавьте к `verify` флаг `--s3-root s3://my-bucket/images`, иначе подготовка остановится с ошибкой `S3 image path is outside approved S3 roots`.

## Синтаксис и аргументы

```text
cveta2 upload-dataset PREPARED_DIR [--force-resplit]
```

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `PREPARED_DIR` | обязателен | Каталог, подготовленный `cveta2 verify`. |
| `--force-resplit` | выключен | Разрешить другой split у изображений, уже опубликованных в родителе. |
| `-h`, `--help` | | Показать справку. |

Проект ClearML, имя датасета, `output_uri`, адрес API классов и корни изображений команда берёт из `dataset.yaml` каталога. Флагами их не задать: поправьте `dataset.yaml`.

ClearML читает свой `clearml.conf`; проверить его можно командой [`cveta2 doctor`](doctor.md). Если файлы версии идут в S3-совместимое хранилище (например, MinIO), адрес хранилища для ClearML задаётся отдельно: переменной `AWS_ENDPOINT_URL_S3` или в `clearml.conf`.

## Как это работает

Команда читает `dataset.csv`, `dataset.yaml` и `sources.tar.gz` по одному разу; все три должны быть обычными файлами, не символическими ссылками. Затем она проверяет прочитанное по шагам. Первая непройденная проверка останавливает публикацию, и в ClearML ничего не создаётся.

1. **Назначение.** `dataset.yaml` строго разбирается и содержит `clearml.project` и `clearml.dataset`. Если блока `clearml` нет, добавьте его (см. [dataset.yaml](../dataset-format.md#datasetyaml)).
2. **Родитель.** Команда ищет родительский датасет ([parent dataset](../../GLOSSARY.md)): последнюю завершённую неархивную версию с этим именем ровно в этом проекте. Если назначение то же, что записал `verify` в `report.json`, версия должна совпасть с записанной. Иначе после `verify` появилась новая версия: запустите `cveta2 verify` заново, чтобы подготовить датасет поверх неё. Если записи в `report.json` нет или вы поменяли назначение в `dataset.yaml`, команда предупреждает и продолжает. Родитель, в `dataset.yaml` которого есть блок `managed`, — управляемый датасет: такие версии публикует `cveta2 dataset publish`; выберите другое `clearml.dataset`.
3. **Классы.** Команда запрашивает API классов по `api_url` и сверяет его с классами родителя. Имена, `prod_id` и `alt_names` в `dataset.yaml` должны совпасть с результатом. Отметки `empty` — ваш выбор, их команда не сверяет. Если классы не совпали, верните их в `dataset.yaml` или запустите `cveta2 verify` заново.
4. **Изображения и хранилища.** Локальные корни из `images.local_root` существуют и читаются. Файл каждого `image_path` существует; пропавшие файлы верните или удалите их строки из `dataset.csv`. Каждый `image_path` лежит внутри локального корня; иначе добавьте каталог в `images.local_root`. Каждый непустой `s3_image_path` лежит внутри ровно одного корня `images.s3_root`, и каждый корень S3 можно прочитать списком. Если `clearml.output_uri` — адрес S3, его бакет существует и доступен; пустой бакет подходит.
5. **Строки.** `dataset.csv` проверяется с открытием каждого изображения: ни одной отклонённой строки и ни одного исправления, у каждой строки split, в `train` и `val` есть изображения, в `train` есть bbox. У каждого класса без `empty: true` есть хотя бы один bbox; иначе отметьте класс `empty: true` в `dataset.yaml` или выгрузите данные, где он есть. Изображение, которое есть в `dataset.csv` родителя (то же `image_name`), должно остаться в опубликованном split ([stable split](../../GLOSSARY.md)); верните split или запустите команду с `--force-resplit`.
6. **Список задач.** `sources.tar.gz` должен содержать четыре файла выгрузки; с другими файлами он не сравнивается. Из него и текущего `dataset.csv` заново строится `tasks.yaml` ([task manifest](../../GLOSSARY.md)) и перезаписывается в каталоге. Строки, пары `task_id` и `image_name` которых нет в архиве, принимаются: в `tasks.yaml` попадают только задачи, с которыми строки связаны, и команда печатает, сколько строк связать не удалось.
7. **Ещё раз родитель.** Прямо перед публикацией родитель ищется ещё раз, потому что предыдущие шаги могут идти долго. Если он изменился, запустите `cveta2 upload-dataset` ещё раз.
8. **Публикация.** В ClearML создаётся новый датасет с проектом и именем из `dataset.yaml`; родитель — найденный родительский датасет (или без родителя, если его нет). Если в `dataset.yaml` задан `clearml.output_uri`, файлы версии хранятся там. Из новой версии удаляются унаследованные от родителя файлы, затем добавляются ровно четыре файла: `dataset.csv`, `dataset.yaml`, `tasks.yaml`, `sources.tar.gz`. Публикуются байты, прочитанные в начале, и новый `tasks.yaml`. Команда загружает их без повторных попыток, проверяет список файлов, завершает (finalize) версию и проверяет список ещё раз.

Изображения в ClearML не загружаются: публикуются только четыре файла. CVAT и S3 команда не меняет. В каталоге она перезаписывает `tasks.yaml` (шаг 6) и после публикации пишет `publication.json`.

## Что можно править

Любой файл каталога, если результат проходит проверки выше: удалить строки из `dataset.csv`, поправить bbox или split, отметить класс `empty: true`, изменить `output_uri` или корни изображений в `dataset.yaml`. Хешей, которые запрещали бы правки, нет. `tasks.yaml` править бесполезно: команда строит его заново. Если вы изменили проект или имя датасета в `dataset.yaml`, команда предупредит, что родитель не сверяется с записью `verify`.

## Результат

После успешной публикации команда печатает ID нового датасета и версию, которую назначил ClearML:

```text
Опубликован датасет 1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6, версия 1.0.2.
```

ClearML SDK печатает свои строки о загрузке файлов, например `Uploading dataset changes (4 files compressed to …) …`.

Если ClearML не вернул номер версии, вместо него печатается `назначена сервером`.

Затем команда пишет в каталог `publication.json`: ID и версию датасета, проект, имя и время публикации (см. [publication.json](../dataset-format.md#publicationjson)). Если записать файл не удалось, команда предупреждает, а публикация остаётся успешной. Повторный `upload-dataset` для каталога с `publication.json` предупреждает о прежней публикации и продолжает; обычно его раньше останавливает шаг 2, потому что прежняя публикация стала последней версией.

### Коды завершения

| Код | Когда |
|---|---|
| 0 | Версия создана, загружена и завершена. |
| 1 | Публикация прервана (Ctrl+C). |
| 2 | Любая проверка не прошла; ошибка ClearML, S3 или API классов. |

## Что блокирует публикацию

| Сообщение | Причина | Что делать |
|---|---|---|
| `Expected a regular, nonsymlink file: output/prepared-1/dataset.csv` | Нет `dataset.csv`, `dataset.yaml` или `sources.tar.gz`, или это символическая ссылка: подготовка была заблокирована (`ready: false`) или указан не тот каталог. | Посмотрите `blockers` в `report.json`, исправьте данные и подготовьте заново. |
| `Архив sources.tar.gz повреждён или неполон: …` | Архив испорчен или в нём не четыре файла выгрузки. | Подготовьте заново командой `cveta2 verify`. |
| `Invalid dataset metadata …/dataset.yaml: …` | `dataset.yaml` не разбирается строго: опечатка в ключе, неверный тип. | Исправьте названный ключ. |
| `В dataset.yaml нет назначения публикации: …` | Нет блока `clearml` с `clearml.project` и `clearml.dataset`. | Добавьте блок `clearml`. |
| `После verify появилась новая версия …` | После подготовки в ClearML опубликована другая версия этого датасета. | Запустите `cveta2 verify` заново: новая подготовка возьмёт новую версию как родителя. |
| `Родитель … не содержит dataset.yaml. Выберите новое имя датасета.` | Последняя версия в ClearML опубликована не cveta2. | Укажите другое `clearml.dataset`. |
| `Родитель … — управляемый датасет …` | Датасет с этим именем ведёт `cveta2 dataset`. | Укажите другое `clearml.dataset` или публикуйте через `cveta2 dataset publish`. |
| `Классы dataset.yaml не совпадают с реестром …` | Имя, `prod_id` или `alt_names` класса отличаются от реестра, или реестр изменился после подготовки. | Верните названные классы в `dataset.yaml` или запустите `cveta2 verify` заново. |
| `Cannot use local root …` | Локального корня из `images.local_root` нет или он не читается. | Исправьте `images.local_root`. |
| `Нет файлов изображений из image_path (…)` | Файлы изображений удалены или перемещены. | Верните файлы или удалите их строки из `dataset.csv`. |
| `image_path вне локальных корней images.local_root (…)` | Изображение лежит вне разрешённых каталогов. | Добавьте каталог в `images.local_root`. |
| `S3 image path is outside approved S3 roots: …` | `s3_image_path` вне корней `images.s3_root`. | Добавьте корень в `images.s3_root`. |
| `S3 root prefix does not exist or is empty: s3://my-bucket/images` | Префикс корня S3 из `images.s3_root` пуст или удалён. | Проверьте бакет и `images.s3_root`. |
| `Cannot access S3 root s3://my-bucket; …` или `S3 listing unavailable for s3://my-bucket; …` | Бакета корня S3 или `output_uri` нет, или к нему нет доступа. | Проверьте имя бакета, права и настройку хранилища ClearML (`cveta2 doctor`). |
| `dataset.csv не проходит проверку: …` | Есть строки, которые проверка отклоняет или исправляет, нет split, нет `train` или `val`. | Исправьте или удалите названные строки. |
| `Нет ни одного bbox классов …` | У класса без `empty: true` нет ни одного bbox. | Отметьте класс `empty: true` в `dataset.yaml` или выгрузите данные с ним. |
| `Изображения опубликованы в родителе … с другим split (…)` | Изображение из `dataset.csv` родителя теперь в другом split. | Верните опубликованный split или запустите с `--force-resplit`. |
| `Родитель … изменился во время проверок. Запустите cveta2 upload-dataset ещё раз.` | Новая версия появилась, пока шли проверки. | Запустите команду ещё раз: шаг 2 покажет, что делать дальше. |

Все сообщения выводятся с префиксом `Ошибка публикации:`.

Предупреждения, после которых публикация продолжается:

| Сообщение | Причина |
|---|---|
| `В report.json нет записи verify о назначении и родителе: …` | `report.json` удалён или в нём нет `destination` и `parent`: родитель не сверяется с тем, что видел `verify`. |
| `Назначение в dataset.yaml (…) отличается от записанного verify (…): …` | Проект или имя датасета в `dataset.yaml` изменены после `verify`. |
| `Каталог уже опубликован (publication.json): …` | Каталог уже публиковался. |
| `… строк dataset.csv нельзя связать с задачами из sources.tar.gz; в tasks.yaml они не попали.` | Строки с `task_id` и `image_name`, которых нет в архиве; это не ошибка (сообщение уровня INFO). |

## Сбой во время публикации

Если ошибка случилась после того, как новый датасет создан в ClearML (шаг 8), команда называет его ID:

```text
Ошибка публикации: Publication failed for created ClearML dataset <id>; inspect it before retrying; check ClearML configuration, credentials and connectivity (…)
```

Созданная версия остаётся в ClearML незавершённой. Родительский датасет при этом не меняется, а при поиске родителя учитываются только завершённые версии. Поэтому после устранения причины можно снова запустить `cveta2 upload-dataset` для того же каталога: повторный запуск создаёт и завершает новую версию. Незавершённую версию cveta2 не удаляет; проверьте и удалите её в ClearML сами.

При прерывании (Ctrl+C) после создания датасета команда печатает:

```text
Публикация отменена: Publication interrupted for ClearML dataset <id>; its remote state is uncertain. Inspect it before retrying.
```

и завершается с кодом 1. Проверьте этот датасет в ClearML перед повторным запуском.

## Интерактивный и неинтерактивный режим

Команда ничего не спрашивает. `CVETA2_NO_INTERACTIVE` на неё не влияет.

## Из Python

```python
def upload_dataset(prepared_dir: str | Path, *, force_resplit: bool = False) -> Publication
```

Функция `cveta2.upload_dataset` делает те же проверки и публикацию, что и команда; `force_resplit=True` — то же, что `--force-resplit`. Она возвращает `cveta2.Publication` с полями `dataset_id` и `version` (`None`, если ClearML не вернул версию). Ошибки — подклассы `cveta2.Cveta2Error`.

```python
import cveta2

prepared = cveta2.prepare_dataset(
    "output/fetch",
    output_dir="output/prepared-1",
    options=cveta2.PrepareOptions(
        project="Retail/Datasets",
        dataset_name="retail-shelves",
        api_url="https://classes.example.com/api",
        local_roots=("/home/user/data/images",),
        accept_default_classes=True,
        clean=True,
    ),
)
if prepared.ready:
    publication = cveta2.upload_dataset(prepared.directory)
    print(publication.dataset_id, publication.version)
```

Подробнее об API — на странице [Python API](../python-api.md).

## См. также

- [`cveta2 verify`](verify.md) — проверка CSV и ручная подготовка.
- [`cveta2 dataset`](dataset.md) — управляемые датасеты и `dataset publish`.
- [Формат данных: подготовленный датасет](../dataset-format.md#подготовленный-датасет).
- [Сценарии](../workflows.md).
- [Глоссарий](../../GLOSSARY.md).

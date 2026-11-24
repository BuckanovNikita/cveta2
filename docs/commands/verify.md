# cveta2 verify

Проверяет CSV с аннотациями bbox и показывает отклонённые строки с причинами. С флагом `--bundle` из каталога полной выгрузки ([full fetch](../../GLOSSARY.md)) готовит подготовленный датасет ([prepared bundle](../../GLOSSARY.md)), который затем публикуется в ClearML командой [`upload-dataset`](upload-dataset.md).

У команды два режима:

- **проверка CSV** — один CSV-файл, ничего не отправляется по сети;
- **ручная подготовка ([bundle preparation](../../GLOSSARY.md))** — флаг `--bundle`, на вход каталог с четырьмя файлами полной выгрузки ([partition outputs](../../GLOSSARY.md)), команда обращается к API классов, к ClearML и к S3.

## Примеры

Проверить `dataset.csv` по профилю `cveta2` и только напечатать итог:

```bash
cveta2 verify output/dataset.csv
```

Проверить CSV по профилю `clearml-yolo`, открыть каждое изображение и записать отчёт и очищенный CSV в новый каталог:

```bash
cveta2 verify output/train.csv --profile clearml-yolo --check-images --clean --output-dir output/verify-1
```

Подготовить датасет для ClearML без вопросов в терминале:

```bash
cveta2 verify ~/data/fetch --bundle \
  --project "Retail/Datasets" --dataset-name retail-shelves \
  --api-url https://classes.example.com/api \
  --local-root ~/data/images --s3-root s3://my-bucket/images \
  --accept-default-classes --empty-class 10 \
  --clean --output-dir output/prepared-1 --non-interactive
```

## Синтаксис и аргументы

```text
cveta2 verify [-h] [--profile {cveta2,clearml-yolo}] [--check-images]
              [--image-root IMAGE_ROOT] [--iou-threshold IOU_THRESHOLD]
              [--clean] [--output-dir OUTPUT_DIR] [--bundle]
              [--project PROJECT] [--dataset-name DATASET_NAME]
              [--api-url API_URL] [--local-root LOCAL_ROOT]
              [--s3-root S3_ROOT] [--empty-class EMPTY_CLASS]
              [--accept-default-classes] [--accept-class-changes]
              [--non-interactive]
              input
```

Общие аргументы:

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `input` | обязателен | Путь к CSV. С `--bundle` — каталог полной выгрузки с файлами `dataset.csv`, `obsolete.csv`, `in_progress.csv`, `deleted.csv`. |
| `--clean` | выкл. | Подтверждение очистки ([cleanup acceptance](../../GLOSSARY.md)): разрешить убрать отклонённые строки и применить исправления. Требует `--output-dir`. |
| `--output-dir` | нет | Новый каталог для отчёта (проверка CSV) или для подготовленного датасета (`--bundle`). Каталог не должен существовать. Обязателен с `--clean` и с `--bundle`. |
| `--bundle` | выкл. | Включить ручную подготовку вместо проверки CSV. |
| `-h`, `--help` | | Показать справку. |

Аргументы проверки CSV (с `--bundle` их нельзя менять, иначе ошибка):

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `--profile` | `cveta2` | Профиль проверки ([verification profile](../../GLOSSARY.md)): `cveta2` или `clearml-yolo`. С `--bundle` не используется: подготовка всегда проверяет по правилам `clearml-yolo`. |
| `--check-images` | выкл. | Открыть и декодировать каждое локальное изображение: проверить, что файл есть и читается, и сверить размеры. |
| `--image-root` | нет | Каталог, в котором искать изображение `image_name`, если ячейка `image_path` пустая. |
| `--iou-threshold` | `0.99` | Порог IoU для поиска почти одинаковых bbox и конфликтов классов. Число больше 0 и не больше 1. |

Аргументы ручной подготовки (без `--bundle` любой из них даёт ошибку `Настройки публикации требуют --bundle.`):

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `--project` | обязателен с `--bundle` | Проект ClearML. |
| `--dataset-name` | вопрос в терминале | Имя датасета в ClearML. |
| `--api-url` | `api_url` родительского датасета | Адрес API классов (HTTP или HTTPS, без логина и пароля в адресе). |
| `--local-root` | корни родительского датасета | Разрешённый локальный каталог с изображениями. Можно повторять. |
| `--s3-root` | корни родительского датасета | Разрешённый префикс `s3://bucket/prefix`. Можно повторять. |
| `--empty-class` | нет | Номер класса (`number` в API классов), который надо пометить как исключённый класс ([empty class](../../GLOSSARY.md)). Можно повторять. |
| `--accept-default-classes` | выкл. | Новые классы из API не исключать и не спрашивать о них. |
| `--accept-class-changes` | выкл. | Подтвердить добавления и переименования классов по сравнению с родительским датасетом. |
| `--non-interactive` | выкл. | Не задавать вопросов: если решения не хватает, завершиться с ошибкой. |

## Проверка CSV

### Как это работает

1. Команда читает CSV как текст в UTF-8. Значения ячеек не преобразуются. Если в заголовке есть пустые или повторяющиеся имена столбцов или в строке другое число ячеек, команда сразу завершается с кодом 2.
2. Проверяются столбцы и значения каждой ячейки по выбранному профилю. Если нет обязательного столбца, это структурная ошибка: отклоняются все строки. Изображение, в котором хотя бы одна ячейка не прошла проверку, сразу исключается из следующих шагов, поэтому другие его проблемы (например, `out_of_bounds`) не попадают в отчёт: остальные строки получают код `image_quarantined`.
3. Строки группируются по изображению. В профиле `cveta2` группа — это пара `image_name` и `task_id`, в профиле `clearml-yolo` — только `image_name`.
4. Проверяется согласованность внутри группы: пути, split, размеры, вид записей.
5. С `--check-images` каждое изображение открывается один раз. Путь берётся из `image_path`; если ячейка пустая, а задан `--image-root`, — из `--image-root`/`image_name`. Относительный путь считается от каталога, где лежит CSV. Адреса вида `s3://…` не читаются.
6. Проверяются границы bbox. В профиле `clearml-yolo` bbox, который выходит за край меньше чем на 10 пикселей, обрезается по краю изображения. Обрезка не делается, если в изображении есть другая ошибка. Затем в `clearml-yolo` ищутся конфликты классов (`class_conflict`).
7. Если у изображения отклонена хотя бы одна строка, отклоняются все строки этого изображения (код `image_quarantined`).
8. Среди оставшихся строк ищутся полные дубликаты строк и почти одинаковые bbox (IoU не меньше `--iou-threshold`). Отклоняется только более поздняя строка; остальные строки изображения остаются.
9. Команда печатает итог и все найденные проблемы. С `--output-dir` пишет файлы отчёта.

Исходный CSV команда не меняет.

### Профили

| | `cveta2` | `clearml-yolo` |
|---|---|---|
| Для чего | CSV, который пишет cveta2 (`fetch`, `fetch-task`, `merge`) | CSV для обучения |
| Обязательные столбцы | `image_name`, `image_width`, `image_height`, `instance_shape`, `instance_label`, `bbox_x_tl`, `bbox_y_tl`, `bbox_x_br`, `bbox_y_br` | `image_name`, `image_path`, `instance_label`, `bbox_x_tl`, `bbox_y_tl`, `bbox_x_br`, `bbox_y_br`, `split` |
| Какие столбцы проверяются | все известные столбцы cveta2 | только обязательные и `image_width`, `image_height`, `width`, `height`; остальные столбцы переносятся без проверки |
| Пустой `split` | разрешён | запрещён |
| Строка без bbox | `instance_shape` = `none` или `deleted`, метка и координаты пустые | пустые метка и все четыре координаты |
| Минимальный bbox | ширина и высота больше 0 | ширина и высота больше 2 пикселей, площадь больше 2 |
| Выход bbox за край изображения | строка отклоняется | обрезка, если на каждой стороне меньше 10 пикселей |
| Конфликт классов | не проверяется | проверяется |
| Почти одинаковые bbox | сравниваются все bbox изображения, метка не учитывается | сравниваются bbox одного класса |

Столбцы описаны на странице [Формат данных](../dataset-format.md#столбцы-csv).

### Правила

Строка с любой из этих проблем попадает в отклонённые строки ([broken rows](../../GLOSSARY.md)). В столбце «Исправление» указано, что `--clean` может исправить вместо отклонения.

Значения ячеек:

| Код | Что отклоняется | Исправление |
|---|---|---|
| `missing_column` | Нет обязательного столбца профиля. Структурная ошибка: отклоняются все строки. | нет, `--clean` невозможен |
| `invalid_image_name` | Пустое `image_name`, `.` или `..`, или имя с `/` или `\`. | нет |
| `invalid_image_path` | Пустой `image_path` (только `clearml-yolo`). | нет |
| `invalid_shape` | `instance_shape` не `box`, `none` или `deleted` (`cveta2`). | нет |
| `invalid_label` | У bbox пустая метка (label). В `cveta2` метка должна быть текстом; в `clearml-yolo` допустима и числовая метка. | нет |
| `missing_bbox` | У bbox заполнены не все четыре координаты. | нет |
| `invalid_coordinate` | Координата не конечное число. | нет |
| `negative_coordinate` | Отрицательная координата. | в `clearml-yolo` — обрезка до 0, если выход меньше 10 пикселей |
| `invalid_box_area` | Ширина или высота bbox не больше 0 (`cveta2`) или не больше 2 пикселей, либо площадь не больше 2 (`clearml-yolo`). | нет |
| `invalid_negative` | Строка без bbox (`none`, `deleted` или пустая метка) содержит метку или координаты. | нет |
| `invalid_dimension` | `image_width`, `image_height`, `width`, `height` — не положительное целое. Для строк `deleted` в `cveta2` разрешён 0. | нет |
| `invalid_integer` | `task_id`, `frame_id`, `annotation_id` — не целое число от 0; `z_order` — не целое. | нет |
| `invalid_boolean` | `occluded`, `task_completed` — не `true`/`false` (в любом регистре, например `True`) и не число 0 или 1 (`1.0` тоже подходит). | нет |
| `invalid_rotation` | `rotation` вне диапазона от 0 до 360. | нет |
| `invalid_confidence` | `confidence` вне диапазона от 0 до 1. | нет |
| `invalid_attributes` | `attributes` — не JSON-объект со строковыми ключами и значениями. | нет |
| `invalid_split` | `split` не `train`, `val` или `test`. Пустое значение запрещено в `clearml-yolo`. | нет |
| `invalid_job_stage` | `job_stage` не `annotation`, `validation` или `acceptance`. | нет |
| `invalid_job_state` | `job_state` не `new`, `in progress`, `completed` или `rejected`. | нет |
| `invalid_issue_state` | `issue_state` не `new` и не список `open`/`resolved`, разделённый ` \| `. | нет |

Согласованность изображения:

| Код | Что отклоняется | Исправление |
|---|---|---|
| `mixed_image_kinds` | В одном изображении смешаны bbox, строки без bbox и строки `deleted`. | нет |
| `path_conflict` | У одного изображения разные пути, или один путь у разных `image_name`. | нет |
| `split_conflict` | Одно изображение в разных split. | нет |
| `invalid_local_path` | `image_path` — удалённый адрес (например, `s3://…`) или путь нельзя разобрать. | нет |
| `path_name_mismatch` | Имя файла в `image_path` не совпадает с `image_name`. | нет |
| `dimension_conflict` | Строки одного изображения указывают разные размеры, или `image_width`/`image_height` не совпадают с `width`/`height`. | нет |
| `image_dimension_mismatch` | Размеры в CSV не совпадают с размерами файла (только с `--check-images`). | нет |
| `media_missing` | Файла изображения нет (только с `--check-images`). | нет |
| `media_unreadable` | Файл не декодируется или у строки нет локального пути (только с `--check-images`). | нет |
| `out_of_bounds` | bbox выходит за границы изображения. Размер берётся из файла (с `--check-images`) или из столбцов размеров. | в `clearml-yolo` — обрезка по краю, если на каждой стороне выход меньше 10 пикселей и после обрезки bbox не меньше минимального |
| `image_quarantined` | Остальные строки изображения, в котором отклонена хотя бы одна строка. | нет |

Дубликаты и пересечения (проверяются после отклонения изображений):

| Код | Что отклоняется | Исправление |
|---|---|---|
| `class_conflict` | Два bbox разных классов с IoU не меньше `--iou-threshold` (только `clearml-yolo`). Отклоняются оба, а с ними всё изображение (`image_quarantined`). | нет |
| `duplicate_row` | Строка, полностью совпадающая с более ранней; отклоняется только поздняя. В `clearml-yolo` сравниваются только обязательные столбцы профиля. | нет |
| `high_iou` | bbox с IoU не меньше `--iou-threshold` относительно более раннего bbox того же изображения; отклоняется только поздний. | нет |

Предупреждения строку не отклоняют: `unknown_columns` (лишние столбцы в профиле `cveta2`, сохраняются без проверки), `unscoped_task` (у одного изображения часть строк с `task_id`, часть без), `bounds_unchecked` (размер изображения неизвестен, правая и нижняя граница не проверены), `rotation_ignored` (у bbox есть поворот, IoU считается по координатам без поворота), `empty_dataset` (в CSV нет строк).

### Что делает --clean

Без `--clean` любая отклонённая строка или предлагаемое исправление означает, что CSV не готов: код завершения 1.

С `--clean` и `--output-dir` команда:

- пишет `clean.csv` — очищенный CSV ([clean CSV](../../GLOSSARY.md)): все неотклонённые строки в исходном порядке и со всеми столбцами, с применёнными исправлениями (обрезка bbox);
- завершается с кодом 0, даже если строки были отклонены.

Структурную ошибку (например, нет обязательного столбца) очистить нельзя: команда завершается с кодом 2 и не создаёт каталог.

Пример исправления в выводе:

```text
bbox_clipped строка 8: Clipped image-boundary overflow below 10 px per edge; before ('103.17', '18.20', '645.0', '315.36'); after ('103.17', '18.20', '640', '315.36').
```

### Результат

Команда всегда печатает итог и по строке на каждую проблему (номера строк считаются от 0, без строки заголовка):

```text
Проверка: 31 строк; допустимых 16, отклонённых 15.
out_of_bounds строка 10: Box extends outside image bounds 0..640 x 0..428; image/task is rejected.
image_quarantined строка 11: Another malformed record quarantined this entire image/task.
duplicate_row строка 30: Later full-row duplicate.
```

С `--output-dir` команда создаёт каталог и пишет в него:

| Файл | Когда | Содержимое |
|---|---|---|
| `report.json` | всегда | Отчёт проверки ([verification report](../../GLOSSARY.md)): профиль, `is_valid`, `requires_cleanup`, `structural_errors`, счётчики строк и изображений, номера допустимых и отклонённых строк, выполненные и пропущенные проверки, список всех проблем. |
| `broken.csv` | всегда | Отклонённые строки без изменений и три столбца: `__validator_row_position` (номер строки), `__validator_reason_codes` и `__validator_reasons` (JSON-списки кодов и сообщений). |
| `clean.csv` | только с `--clean` | Очищенный CSV. |

Каталог `--output-dir` не должен существовать и не должен совпадать с каталогом, где лежит входной CSV.

### Коды завершения

| Код | Когда |
|---|---|
| 0 | Нет отклонённых строк и исправлений, или задан `--clean` и нет структурных ошибок. |
| 1 | Есть отклонённые строки или исправления без `--clean`; структурная ошибка (нет обязательного столбца); проверка прервана (Ctrl+C). |
| 2 | Ошибка аргументов, CSV не читается, каталог `--output-dir` уже есть, `--clean` при структурной ошибке. |

### Частые ошибки

```text
Ошибка проверки: Для --clean и --bundle требуется --output-dir.
```

Добавьте `--output-dir` с новым каталогом.

```text
Ошибка проверки: Cannot write verification output: [Errno 17] File exists: 'output/verify-1'
```

Каталог отчёта уже есть. Укажите новый каталог: команда не перезаписывает старые отчёты.

```text
Ошибка проверки: Cannot write verification output: Reports require a new directory separate from the input.
```

`--output-dir` совпадает с каталогом входного CSV. Укажите другой каталог.

```text
Ошибка проверки: Cannot load verification input output/train.csv: CSV record 2 has 1 cells; expected 2.
```

В строке файла другое число ячеек, чем в заголовке. Исправьте CSV.

```text
Ошибка проверки: Cannot write verification output: Structural errors cannot be cleaned away.
```

В CSV нет обязательного столбца, а вы указали `--clean`. Добавьте столбец; `--clean` его не заменит.

```text
invalid_split строка 0: Expected train, val or test (an empty split is allowed only in cveta2): split.
```

Профиль `clearml-yolo` требует split у каждой строки. `fetch` оставляет `split` пустым: заполните его перед проверкой. См. [split](../dataset-format.md#split).

## Ручная подготовка (--bundle)

### Что нужно

- Каталог полной выгрузки со всеми четырьмя файлами. В `dataset.csv` у каждой строки должен быть split `train`, `val` или `test`, а `image_path` — абсолютный локальный путь к изображению. `fetch` оставляет `split` пустым, поэтому заполните его сами. Формат файлов — на странице [Формат данных](../dataset-format.md#файлы-полной-выгрузки).
- Адрес API классов — реестра классов ([class registry](../../GLOSSARY.md)).

### Как это работает

1. Команда проверяет аргументы: нужны `--project` и `--output-dir`; `--check-images`, `--image-root` и изменённый `--iou-threshold` запрещены (изображения проверяются всегда).
2. Нужно имя датасета (`--dataset-name`). Если его нет, команда спрашивает его в терминале.
3. Команда читает все четыре файла из каталога `input`.
4. В ClearML ищется родительский датасет ([parent dataset](../../GLOSSARY.md)): последняя завершённая (finalized) неархивная версия с этим именем ровно в проекте `--project` (без подпроектов). Если она есть, из неё скачивается `dataset.yaml`. Если у родителя нет `dataset.yaml`, команда останавливается. Пока в проекте ClearML нет ни одного датасета, ClearML SDK печатает предупреждение `No projects were found with name(s): ...`. Это не ошибка: проект появится при первой публикации.
5. Адрес API классов берётся из `--api-url`, иначе из `dataset.yaml` родителя. Если адреса нет, команда спрашивает его.
6. Команда запрашивает список классов из API (GET без авторизации, тайм-аут 30 секунд). Классы сопоставляются по номеру класса ([class identity](../../GLOSSARY.md)) — полю `number` в API, в `dataset.yaml` это `prod_id`:
   - класс с новым номером — добавленный;
   - класс с прежним номером и новым именем — переименованный; старое имя сохраняется как псевдоним (`alt_names`), а метки со старым именем в CSV заменяются на каноническое имя класса ([canonical class name](../../GLOSSARY.md));
   - если номер класса из родителя пропал из API, команда останавливается;
   - флаг «исключён» родительских классов сохраняется.
7. Для решений о классах:
   - если есть родитель и классы изменились, нужно подтверждение (`--accept-class-changes` или вопрос);
   - для каждого добавленного класса нужно решить, исключать ли его: `--empty-class <номер>` исключает класс, `--accept-default-classes` оставляет все остальные новые классы обычными. Без них команда спрашивает про каждый класс.
   - `--empty-class` с номером, которого нет в API, — ошибка.
8. Корни изображений = корни родителя плюс `--local-root` и `--s3-root`. Каждый `image_path` из `dataset.csv` должен лежать внутри одного из локальных корней. Если какие-то файлы вне корней, команда печатает их список и спрашивает, разрешить ли их родительские каталоги. Каждое значение `s3_image_path` должно попадать ровно в один корень S3. Каждый корень S3 должен быть доступен для чтения списка объектов (это проверяется через ClearML SDK), а непустой префикс должен существовать.
9. `dataset.csv` проверяется по правилам профиля `clearml-yolo` с открытием каждого изображения (см. [Правила](#правила)) и дополнительно:

   | Код или сообщение | Что отклоняется или блокирует | Исправление |
   |---|---|---|
   | `unknown_class` | Метки нет среди имён и псевдонимов классов API. | нет |
   | `empty_class` | Класс помечен как исключённый. | нет |
   | `class_canonicalized` | Метка — старое имя класса. | замена на каноническое имя |
   | `training_image_format` | Расширение или формат файла не из списка: `avif`, `bmp`, `jp2`, `jpeg`, `jpg`, `mpo`, `png`, `tif`, `tiff`, `webp`. | нет |
   | `training_image_size` | Сторона изображения меньше 10 пикселей. | нет |
   | `image_quarantined` | Остальные строки изображения с отклонённой строкой. | нет |

10. Затем проверяются блокирующие условия ([blocker](../../GLOSSARY.md)). Любое из них делает подготовку неготовой даже с `--clean`:
    - у какой-то строки нет split `train`, `val` или `test`: `Every input row must have a valid train, val or test split assignment.`;
    - структурная ошибка в CSV: `Input CSV has structural validation errors.`;
    - после отклонения не осталось изображений: `No valid images remain for upload.`;
    - нет ни одного изображения в `train` или в `val` (`test` не обязателен): `Required train split has no valid images.` или `Required val split has no valid images.`;
    - в `train` нет ни одного bbox: `At least one valid training box is required.`
11. Из четырёх файлов выводится список задач датасета ([task manifest](../../GLOSSARY.md), `tasks.yaml`): задачи, строки которых остались в очищенном `dataset.csv`, и завершённые задачи ([completed task](../../GLOSSARY.md)), все изображения которых заменены более новыми результатами.
12. Подготовка готова (`ready`), если нет блокирующих условий и либо очистка не нужна, либо задан `--clean`.
13. Команда создаёт каталог `--output-dir` и пишет в него файлы. Она ничего не создаёт в ClearML и ничего не меняет в S3 и CVAT.

Каталог `--output-dir` не должен существовать и не должен лежать внутри каталога `input`. Состав каталога описан на странице [Формат данных](../dataset-format.md#подготовленный-датасет).

### Результат

Всегда пишутся `sources.tar.gz` (архив четырёх файлов), `broken-images.csv` (исходные строки всех изображений, в которых отклонена хотя бы одна строка) и `report.json` (отчёт проверки плюс итог подготовки, см. [report.json](../dataset-format.md#reportjson)). Только при готовности добавляются `dataset.csv`, `dataset.yaml` и `tasks.yaml`.

Вывод готовой подготовки:

```text
Проверка: 30 строк; допустимых 28, отклонённых 2.
empty_class строка 13: Class is marked empty: 'umbrella'
image_quarantined строка 14: Another rejected record quarantined this image.
Отчёт: output/prepared-1
Набор подготовлен. После проверки: cveta2 upload-dataset output/prepared-1
```

Если подготовка не готова, вместо последней строки печатаются блокирующие условия и:

```text
Набор не готов к публикации; исправьте исходные данные или явно разрешите очистку.
```

Перед публикацией просмотрите `report.json`, `broken-images.csv` и `dataset.yaml`. Файлы каталога можно править: `upload-dataset` проверяет их такими, какие они есть (см. [upload-dataset](upload-dataset.md#что-можно-править)).

### Коды завершения

| Код | Когда |
|---|---|
| 0 | Подготовка готова. |
| 1 | Подготовка не готова (каталог с отчётом всё равно создан); вы ответили «нет» на вопрос или прервали команду. |
| 2 | Ошибка аргументов; не хватает решения без терминала; файлы вне корней изображений; ошибка API классов, ClearML или S3; каталог уже есть. |

### Частые ошибки

```text
Ошибка проверки: Для --bundle укажите --project.
```

Добавьте `--project` с проектом ClearML.

```text
Ошибка проверки: Параметры --check-images, --image-root и изменённый --iou-threshold относятся к проверке CSV; bundle всегда проверяет изображения.
```

Уберите эти флаги из команды с `--bundle`.

```text
Ошибка проверки: Исключать класс 'bowl' (1)?
Исключать класс 'broccoli' (2)?
```

Без терминала команда не может спросить про новые классы. Укажите `--empty-class` для классов, которые надо исключить, и `--accept-default-classes` для остальных.

```text
Ошибка проверки: Подтвердите изменения классов: renamed: canine (3)
```

Классы в API изменились с момента родительского датасета. Проверьте изменения и добавьте `--accept-class-changes`. Если в CSV остались старые имена, их замена требует `--clean`.

```text
Ошибка проверки: Укажите разрешённые каталоги изображений:
/home/user/data/images/shelf_0009.jpg
```

Файлы лежат вне разрешённых локальных корней. Добавьте `--local-root` с каталогом, в котором они лежат.

```text
Ошибка проверки: S3 image path is outside approved S3 roots: 'shelf_0009.jpg'
```

В `dataset.csv` заполнен `s3_image_path`, а подходящего `--s3-root` нет. Добавьте `--s3-root s3://my-bucket/images` с бакетом и префиксом, где лежат изображения.

```text
Ошибка проверки: Preparation directory already exists: output/prepared-1
Ошибка проверки: Preparation must be outside the source directory.
```

Каталог `--output-dir` уже есть или лежит внутри каталога `input`. Укажите новый каталог вне выгрузки. Эта проверка идёт в самом конце, после запросов к ClearML и API классов.

```text
Every input row must have a valid train, val or test split assignment.
```

Это блокирующее условие. Заполните `split` у всех строк `dataset.csv` и подготовьте заново.

```text
Ошибка проверки: Родитель <id> не содержит dataset.yaml. Выберите новое имя датасета.
```

В ClearML уже есть датасет с этим именем, но он создан не cveta2. Укажите другое `--dataset-name`.

```text
Ошибка проверки: Class API returned HTTP 404; check the public endpoint
Ошибка проверки: Class API must return a JSON list of valid class definitions
```

Проверьте `--api-url`. API должен отдавать JSON-список объектов с полями `id`, `number`, `name`, `techClass`, `isPeriodical`, `isCritical`, `threshold`.

## Интерактивный и неинтерактивный режим

Проверка CSV ничего не спрашивает.

Ручная подготовка задаёт вопросы, только если стандартный ввод — терминал, не задан `--non-interactive` и `CVETA2_NO_INTERACTIVE` не равно `true`:

| Чего не хватает | Вопрос | Флаг для неинтерактивного режима |
|---|---|---|
| имени датасета | `Укажите имя датасета ClearML.` (ввод текста) | `--dataset-name` |
| адреса API классов | `Укажите URL API классов.` (ввод текста) | `--api-url` |
| решения о новом классе | `Исключать класс '<имя>' (<номер>)?` (да/нет, по умолчанию нет) | `--empty-class`, `--accept-default-classes` |
| подтверждения изменений классов | `Подтвердите изменения классов: …` (да/нет; «нет» отменяет подготовку) | `--accept-class-changes` |
| корней для файлов | `Разрешить каталоги:` и список родительских каталогов файлов (да/нет; «нет» отменяет подготовку) | `--local-root` |

Пустой ответ на текстовый вопрос отменяет подготовку с кодом 1 и сообщением `Проверка отменена.`.

Без терминала недостающее решение даёт ошибку с кодом 2: команда печатает `Ошибка проверки:` и тексты вопросов. Решения проверяются по очереди (имя датасета, адрес API, классы, корни изображений), и команда останавливается на первом шаге, где чего-то не хватает. Поэтому после исправления может появиться следующий вопрос: например, сначала все вопросы о классах, а при следующем запуске — список файлов вне корней. В отличие от других команд здесь не печатается сообщение `Interactive prompt required…` из [неинтерактивного режима](../configuration.md#неинтерактивный-режим).

## Из Python

Функции доступны как `cveta2.verify`, `cveta2.verify_dataframe` и `cveta2.prepare_dataset`. Они ничего не спрашивают в терминале.

```python
def verify(
    path: str | Path,
    *,
    profile: Profile = "cveta2",
    options: ValidationOptions | None = None,
    output_dir: str | Path | None = None,
    clean: bool = False,
) -> ValidationResult

def verify_dataframe(
    frame: pd.DataFrame,
    *,
    profile: Profile = "cveta2",
    options: ValidationOptions | None = None,
) -> ValidationResult

def prepare_dataset(
    source: str | Path,
    *,
    output_dir: str | Path | None = None,
    options: PrepareOptions | None = None,
) -> PreparedDataset
```

- `ValidationOptions(iou_threshold=0.99, check_images=False, image_root=None, base_dir=None, emit_warnings=True)`. `base_dir` — каталог для относительных путей (по умолчанию каталог CSV). С `emit_warnings=True` предупреждения выдаются через модуль `warnings` (класс `cveta2.DatasetWarning`).
- `ValidationResult` содержит `clean` и `broken` (DataFrame), `issues` (список `Issue` с полями `code`, `message`, `severity`, `row_position`, `columns`, `related_rows`, `iou`), свойства `is_valid` и `requires_cleanup`, метод `reasons_for(row_position)`. `verify_dataframe` ничего не пишет на диск.
- `verify` бросает `cveta2.DatasetInputError`, если CSV не читается или каталог отчёта нельзя создать.
- `prepare_dataset(source)` готовит набор из каталога `fetch`, как `cveta2 verify <каталог>`. Без `output_dir` набор пишется рядом с `source`: в `<source>-prepared`, а если он занят — в `<source>-prepared-2`, `-3` и так далее. Указанный `output_dir` не должен существовать. `options=None` означает `PrepareOptions()`.
- `PrepareOptions(project=None, dataset_name=None, output_uri=None, api_url=None, local_roots=(), s3_roots=(), class_empty={}, accept_default_classes=False, accept_class_changes=False, clean=True)`. Незаданное значение берётся из черновика `dataset.yaml` в `source`, а `api_url` — затем из родительского датасета. Корни изображений (`local_roots`, `s3_roots`) складываются с корнями черновика и родителя.
  - `project` и `dataset_name` — проект и имя датасета ClearML. Оба необязательны, если они есть в черновике (`clearml.project`, `clearml.dataset`).
  - `output_uri` — куда ClearML загружает файлы датасета; без него — из черновика (`clearml.output_uri`), иначе хранилище ClearML по умолчанию.
  - `class_empty` — словарь «номер класса → исключён ли». `{N: True}` исключает класс. `{N: False}` возвращает класс, исключённый в родительском датасете: без этого его отметка сохраняется. Номер, которого нет в реестре классов, — ошибка.
  - `clean=True` (по умолчанию): строки, которые отклонила проверка, не попадают в набор и не мешают ему. С `clean=False` такие строки блокируют набор.
  - `accept_default_classes` и `accept_class_changes` принимаются и ничего не делают: о классах больше ничего не спрашивается, изменения классов попадают в `changes` и `report.json`.
- Если не хватает решения, `prepare_dataset` бросает `cveta2.MissingDecisions` с кортежем `decisions`; у каждого решения есть `kind`, `message` и `choices`. Значения `kind`: `project`, `dataset_name`, `api_url` (URL API классов), `local_roots` (в `choices` — пути изображений вне разрешённых каталогов). Прочие ошибки — подклассы `cveta2.Cveta2Error`. Пустой или относительный `image_path` и отсутствующий файл изображения — тоже ошибка: тогда ничего не пишется.
- `PreparedDataset` содержит поля:
  - `directory`, `ready`, `validation`, `metadata`, `tasks`;
  - `blockers` — что не даёт записать `dataset.csv`, `dataset.yaml` и `tasks.yaml` (тогда `ready` ложно). Например, класс без единого bbox, который не исключён;
  - `pending` — что `upload-dataset` потребует, но пока не выполнено: пустой `split`, нет изображений в `train` или `val`, нет ни одного bbox в `train`. Если `ready`, набор при этом записан;
  - `changes` — добавленные и переименованные классы реестра;
  - `mark_changes` — классы, у которых отметка «исключён» отличается от родительской;
  - `dropped_local_roots` — локальные корни родителя, которых нет на этом компьютере;
  - `split_prefilled` — сколько изображений получили `split` из `dataset.csv` родителя. Заполняются только пустые ячейки.

```python
import cveta2

result = cveta2.verify(
    "output/train.csv",
    profile="clearml-yolo",
    options=cveta2.ValidationOptions(check_images=True, emit_warnings=False),
)
print(result.is_valid, len(result.clean), len(result.broken))
for issue in result.issues:
    print(issue.code, issue.row_position, issue.message)

try:
    # Назначение, API классов и корни берутся из черновика output/fetch/dataset.yaml.
    prepared = cveta2.prepare_dataset(
        "output/fetch",  # ~ в пути не раскрывается
        options=cveta2.PrepareOptions(class_empty={10: True, 12: False}),
    )
    print(prepared.ready, prepared.directory)  # абсолютный путь к output/fetch-prepared
    for item in prepared.pending:
        print("перед публикацией:", item)
except cveta2.MissingDecisions as error:
    for decision in error.decisions:
        print(decision.kind, decision.message)
```

Подробнее об API — на странице [Python API](../python-api.md).

## См. также

- [`cveta2 upload-dataset`](upload-dataset.md) — публикация подготовленного датасета в ClearML.
- [`cveta2 dataset`](dataset.md) — управляемая подготовка по описанию в общей конфигурации.
- [`cveta2 fetch`](fetch.md) — полная выгрузка проекта.
- [Формат данных](../dataset-format.md) — столбцы CSV и состав подготовленного датасета.
- [Сценарии](../workflows.md).
- [Глоссарий](../../GLOSSARY.md).

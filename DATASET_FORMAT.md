# Формат выходных данных cveta2

cveta2 сохраняет bbox-аннотации в CSV-файлы. Тип записи определяется полем `instance_shape`: `"box"` (аннотация), `"none"` (изображение без аннотаций) или `"deleted"` (удалённое изображение).

## Выходные файлы

### `cveta2 fetch`

| Файл | Описание |
|---|---|
| `dataset.csv` | Данные из последней завершённой задачи для каждого неудалённого изображения |
| `obsolete.csv` | Данные из старых завершённых задач + данные для изображений, удалённых в последней задаче |
| `in_progress.csv` | Данные из незавершённых задач |
| `deleted.csv` | Удалённые изображения в том же CSV-формате, что и `dataset.csv` (`instance_shape="deleted"`) |
| `raw.csv` | (только с `--raw`) Полный необработанный CSV со всеми строками |

### `cveta2 fetch-task`

| Файл | Описание |
|---|---|
| `dataset.csv` | Все аннотации выбранных задач (без разбиения) |
| `deleted.csv` | Удалённые изображения (`instance_shape="deleted"`) |

## Формат данных

`CvatClient.fetch_annotations()` возвращает `ProjectAnnotations`, `CvatClient.fetch_one_task()` — `TaskAnnotations`:

- `ProjectAnnotations` — результат по всем задачам: `annotations: list[AnnotationRecord]`, `deleted_images: list[DeletedImage]`
- `TaskAnnotations` — результат по одной задаче: `task_id`, `task_name`, `annotations`, `deleted_images`. Метод `TaskAnnotations.merge(list)` объединяет несколько задач в `ProjectAnnotations`

`AnnotationRecord` — это `BBoxAnnotation` (`instance_shape="box"`) или `ImageWithoutAnnotations` (`instance_shape="none"`). Оба типа содержат `image_name`, `task_id`, `frame_id` и реализуют `to_csv_row()`.

### BBoxAnnotation

| Поле | Тип | Описание |
|---|---|---|
| `image_name` | `str` | Имя файла изображения |
| `image_width` | `int` | Ширина изображения (px) |
| `image_height` | `int` | Высота изображения (px) |
| `instance_shape` | `"box"` | Тип фигуры (дискриминатор) |
| `instance_label` | `str` | Название метки |
| `bbox_x_tl` | `float` | X верхнего левого угла |
| `bbox_y_tl` | `float` | Y верхнего левого угла |
| `bbox_x_br` | `float` | X нижнего правого угла |
| `bbox_y_br` | `float` | Y нижнего правого угла |
| `task_id` | `int` | ID задачи в CVAT |
| `task_name` | `str` | Название задачи |
| `task_status` | `str` | Статус задачи (completed, annotation, ...) |
| `task_updated_date` | `str` | Дата/время последнего обновления задачи |
| `created_by_username` | `str` | Имя пользователя, создавшего аннотацию |
| `frame_id` | `int` | Индекс кадра внутри задачи |
| `split` | `"train" \| "val" \| "test" \| None` | Сплит датасета (см. примечание ниже) |
| `subset` | `str` | Подмножество из CVAT (поле задачи) |
| `occluded` | `bool` | Объект перекрыт |
| `z_order` | `int` | Порядок наложения |
| `rotation` | `float` | Угол поворота (0–360) |
| `source` | `str` | Источник аннотации (manual/auto) |
| `annotation_id` | `int \| None` | ID аннотации в CVAT |
| `confidence` | `float \| None` | Уверенность предсказания (заполняется при конвертации из YOLO) |
| `issue_text` | `str` | Текст issue кадра из CVAT (комментарии; см. примечание ниже), `""` если issues нет |
| `issue_state` | `str` | Состояние issue: `open`, `resolved` или `""` (нет issue); значение `new` зарезервировано для загрузки |
| `attributes` | `dict[str, str]` | Пользовательские атрибуты |
| `s3_image_path` | `str \| None` | Полный S3-ключ относительно бакета (например `prefix/img.jpg` или `prefix/2026-02/img.jpg` для новых загрузок), `None` если неизвестен |
| `image_path` | `str \| None` | Абсолютный локальный путь к файлу изображения, `None` если неизвестен |

> **Поле `split`** — конвенция cveta2, а не CVAT. При выгрузке из CVAT (`fetch`) всегда `None`. Заполняется вручную или при конвертации. При загрузке обратно в CVAT (`upload`) игнорируется.

### Issues (`issue_text` / `issue_state`)

Issues в CVAT привязаны к кадру (изображению), поэтому обе колонки дублируются на всех строках кадра — и на bbox-строках, и на строках без аннотаций.

**При выгрузке (`fetch`):**

- Текст одного issue — это его комментарии, соединённые через `"; "` в порядке создания.
- Если на кадре несколько issues, обе колонки соединяются через `" | "` в одном и том же порядке: N-й фрагмент `issue_text` соответствует N-му фрагменту `issue_state` (позиционное выравнивание).
- `issue_state` принимает значения `open` (не решён), `resolved` (решён) или `""` (issues нет).
- **Внимание:** разделитель `" | "` — соглашение формата. Если текст комментария сам содержит `" | "`, однозначно разбить колонку обратно на отдельные issues нельзя.

**При загрузке (`upload`):**

- Строки со значением `issue_state = "new"` и непустым `issue_text` превращаются в открытые issues на созданной задаче; `issue_text` становится первым комментарием.
- Дубликаты по паре (`image_name`, `issue_text`) создаются один раз.
- Позиция issue — bbox строки, если все четыре координаты заполнены, иначе весь кадр.
- Строки с `issue_state` = `open`, `resolved` или `""` при загрузке игнорируются.

### ImageWithoutAnnotations

Изображения без bbox-аннотаций. Включаются в CSV с пустыми bbox-полями. Отличаются от `BBoxAnnotation` значением `instance_shape="none"`.

| Поле | Тип | Описание |
|---|---|---|
| `image_name` | `str` | Имя файла изображения |
| `image_width` | `int` | Ширина изображения (px) |
| `image_height` | `int` | Высота изображения (px) |
| `instance_shape` | `"none"` | Тип фигуры (дискриминатор) |
| `task_id` | `int` | ID задачи в CVAT |
| `task_name` | `str` | Название задачи |
| `task_status` | `str` | Статус задачи |
| `task_updated_date` | `str` | Дата/время последнего обновления задачи |
| `frame_id` | `int` | Индекс кадра внутри задачи |
| `split` | `"train" \| "val" \| "test" \| None` | Сплит датасета |
| `subset` | `str` | Подмножество из CVAT |
| `issue_text` | `str` | Текст issue кадра (см. раздел про issues выше), `""` если issues нет |
| `issue_state` | `str` | Состояние issue: `open`, `resolved` или `""` |
| `s3_image_path` | `str \| None` | Полный S3-ключ относительно бакета, `None` если неизвестен |
| `image_path` | `str \| None` | Абсолютный локальный путь к файлу, `None` если неизвестен |

### DeletedImage

Запись об удалённом изображении. Сохраняется в `deleted.csv` с `instance_shape="deleted"`, чтобы формат столбцов совпадал с `dataset.csv`.

| Поле | Тип | Описание |
|---|---|---|
| `image_name` | `str` | Имя файла изображения |
| `image_width` | `int` | Ширина изображения (px), по умолчанию `0` |
| `image_height` | `int` | Высота изображения (px), по умолчанию `0` |
| `instance_shape` | `"deleted"` | Тип фигуры (дискриминатор) |
| `task_id` | `int` | ID задачи |
| `task_name` | `str` | Название задачи |
| `task_status` | `str` | Статус задачи |
| `task_updated_date` | `str` | Дата обновления задачи |
| `frame_id` | `int` | Индекс кадра |
| `subset` | `str` | Подмножество из CVAT |
| `s3_image_path` | `str \| None` | Полный S3-ключ относительно бакета, `None` если неизвестен |
| `image_path` | `str \| None` | Абсолютный локальный путь к файлу, `None` если неизвестен |

### DownloadStats

| Поле | Тип | Описание |
|---|---|---|
| `downloaded` | `int` | Количество скачанных файлов |
| `cached` | `int` | Пропущено (уже существовали локально) |
| `failed` | `int` | Ошибки при скачивании |
| `total` | `int` | Общее количество изображений |

### UploadStats

| Поле | Тип | Описание |
|---|---|---|
| `uploaded` | `int` | Количество загруженных файлов на S3 |
| `skipped_existing` | `int` | Пропущено (уже существовали на S3) |
| `failed` | `int` | Ошибки при загрузке |
| `total` | `int` | Общее количество изображений |

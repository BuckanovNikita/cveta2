# Документация cveta2

Указатель всех страниц. Термины cveta2 с русскими названиями — в [глоссарии](../GLOSSARY.md).

## С чего начать

- [README](../README.md) — что такое cveta2, установка, быстрый старт.
- [Сценарии работы](workflows.md) — первая выгрузка, обновление датасета, предразметка, публикация в ClearML.
- [Конфигурация](configuration.md) — личная ([personal configuration](../GLOSSARY.md)) и общая конфигурация в YAML, переменные окружения, неинтерактивный режим.

## Команды

Настройка:

- [setup](commands/setup.md) — логин и пароль CVAT, подключение общей конфигурации ([shared configuration](../GLOSSARY.md)).
- [setup-cache](commands/setup-cache.md) — каталоги кэша изображений ([image cache](../GLOSSARY.md)) и кэша аннотаций ([annotation cache](../GLOSSARY.md)).
- [doctor](commands/doctor.md) — проверка конфигурации, ключей S3, подключения ClearML и прав на кэш.

Выгрузка из CVAT:

- [fetch](commands/fetch.md) — полная выгрузка ([full fetch](../GLOSSARY.md)) проекта в четыре CSV-файла.
- [fetch-task](commands/fetch-task.md) — выгрузка выбранных задач (task).
- [whats-new](commands/whats-new.md) — завершённые задачи ([completed task](../GLOSSARY.md)), которых нет в прошлой выгрузке.
- [s3-sync](commands/s3-sync.md) — скачать файлы из корня синхронизации ([sync root](../GLOSSARY.md)) проекта в S3 в кэш изображений.

Работа с CSV:

- [merge](commands/merge.md) — объединить старый и новый датасет с сохранением split.
- [convert](commands/convert.md) — CSV в YOLO и COCO, YOLO в CSV.

Изменения в CVAT:

- [upload](commands/upload.md) — создать задачу из CSV.
- [labels](commands/labels.md) — посмотреть и изменить метки (label) проекта.
- [ignore](commands/ignore.md) — список игнорируемых задач ([ignore list](../GLOSSARY.md)): их выгрузка пропускает.
- [task](commands/task.md) — пометить кадры (frame) удалёнными, удалить аннотации метки или задачу, сменить stage и state.

Проверка и публикация в ClearML:

- [verify](commands/verify.md) — проверка CSV и сборка подготовленного датасета ([prepared bundle](../GLOSSARY.md)) через `--bundle`.
- [upload-dataset](commands/upload-dataset.md) — публикация датасета после `verify --bundle`.
- [dataset](commands/dataset.md) — управляемые датасеты: выгрузка, подготовка, замечания, публикация, сравнение версий.

## Справочник

- [Формат данных](dataset-format.md) — столбцы CSV, файлы полной выгрузки, каталог подготовленного датасета.
- [Изображения и кэши](images-and-cache.md) — кэш изображений, кэш аннотаций (локально и в S3), состояние загрузки.
- [Python API](python-api.md) — `Connection`, `CvatClient`, исключения, функции без отдельной команды.
- [Глоссарий](../GLOSSARY.md) — термины cveta2 на английском с русскими названиями.

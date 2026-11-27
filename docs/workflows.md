# Сценарии работы

Четыре сценария от начала до конца: первая выгрузка и обучающие данные, обновление датасета, цикл предразметки и публикация в ClearML. Каждый шаг — точная команда и что вы увидите. Все флаги и ошибки описаны на страницах команд, на них ведут ссылки.

Во всех примерах проект CVAT называется `Retail shelves` (ID `123`), каталог результатов — `output/`, кэш изображений — `~/data/images`.

## 1. Первая выгрузка и данные для обучения

Вы получили общую конфигурацию ([global configuration](../GLOSSARY.md)) от команды и хотите получить из проекта CVAT данные в формате YOLO.

1. Подключите общую конфигурацию. Эта команда работает и без терминала:

   ```bash
   cveta2 setup --global-config ~/team/project-config.yaml
   ```

   Затем введите логин и пароль CVAT. `cveta2 setup` без аргументов спрашивает их в терминале. Подробнее — [setup](commands/setup.md), ключи файлов — [Конфигурация](configuration.md).

   ```bash
   cveta2 setup
   ```

2. Укажите, куда складывать изображения. После логина и пароля тот же мастер `cveta2 setup` спрашивает корневой каталог кэша (например `~/data/images`), предлагает для каждого проекта путь `<корень>/<имя проекта>` и спрашивает каталог кэша аннотаций ([annotation cache](../GLOSSARY.md)). Работает только в терминале. Подробнее — [setup](commands/setup.md#мастер-личной-настройки) и [Изображения и кэши](images-and-cache.md).

   ```bash
   cveta2 setup
   cveta2 setup --list
   ```

   `--list` печатает итоговые настройки, в том числе пути кэша, и ничего не меняет.

3. Проверьте настройки:

   ```bash
   cveta2 doctor
   ```

   Код `0` и строка `doctor: обязательные проверки пройдены` значат, что конфигурация в порядке. Предупреждения о ключах AWS, подключении ClearML и правах на каталоги кэша на код не влияют; права исправляет `cveta2 doctor --cache`. Подробнее — [doctor](commands/doctor.md).

4. Сделайте полную выгрузку ([full fetch](../GLOSSARY.md)) проекта:

   ```bash
   cveta2 fetch -p "Retail shelves" -o output/
   ```

   В `output/` появятся четыре файла полной выгрузки ([partition outputs](../GLOSSARY.md)): `dataset.csv`, `obsolete.csv`, `in_progress.csv`, `deleted.csv`. Изображения скачиваются в кэш изображений ([image cache](../GLOSSARY.md)); уже скачанные пропускаются. Для обучения нужен только `dataset.csv`; что лежит в остальных файлах, описано в [Формат данных](dataset-format.md#файлы-полной-выгрузки). Флаги — [fetch](commands/fetch.md).

5. Если вам нужны все файлы из хранилища проекта, а не только изображения с аннотациями (например, для работы без сети), скачайте их:

   ```bash
   cveta2 s3-sync -p "Retail shelves"
   ```

   Команда докачивает только то, чего нет локально, и ничего не удаляет. Для обучения на `dataset.csv` этот шаг не нужен: `fetch` уже скачал его изображения. Подробнее — [s3-sync](commands/s3-sync.md).

6. Назначьте split. `fetch` оставляет столбец `split` пустым. Все строки одного изображения должны попасть в один split, поэтому делите список изображений, а не строки. Скрипт ниже заполняет split только там, где он пуст, поэтому подходит и для сценария 2:

   ```python
   # assign_split.py
   import sys

   import pandas as pd

   src, dst = sys.argv[1], sys.argv[2]
   df = pd.read_csv(src)

   # Изображения, у которых split ещё не назначен.
   missing = df.loc[df["split"].isna(), "image_name"].drop_duplicates()
   images = missing.sample(frac=1.0, random_state=42).tolist()

   n_train = int(len(images) * 0.8)
   n_val = int(len(images) * 0.1)
   split_of = {}
   for i, name in enumerate(images):
       if i < n_train:
           split_of[name] = "train"
       elif i < n_train + n_val:
           split_of[name] = "val"
       else:
           split_of[name] = "test"

   df["split"] = df["split"].fillna(df["image_name"].map(split_of))
   df.to_csv(dst, index=False)
   print(df.groupby("split")["image_name"].nunique())
   ```

   ```bash
   python assign_split.py output/dataset.csv output/dataset-split.csv
   ```

   Скрипт печатает число изображений в каждом split. pandas ставится вместе с cveta2. Правила столбца — [split](dataset-format.md#split).

7. Конвертируйте в YOLO:

   ```bash
   cveta2 convert --to-yolo -d output/dataset-split.csv -o output/yolo --image-dir ~/data/images
   ```

   В `output/yolo` появятся `dataset.yaml`, `images/<split>/` и `labels/<split>/`. Укажите `--image-dir`: `convert` не читает столбец `image_path` и без этого флага ищет изображения только в каталогах раздела `image_cache`. Если изображение не найдено, команда завершается с ошибкой `Ошибка: не найдено N изображений: ...` и ничего не пишет. Для COCO замените `--to-yolo` на `--to-coco`. Подробнее — [convert](commands/convert.md).

## 2. Обновление датасета

У вас есть прошлая выгрузка в `~/data/old/` (все четыре файла) и датасет с назначенным split `~/data/old/dataset-split.csv`. Аннотаторы завершили новые задачи (task).

1. Проверьте, есть ли что забирать:

   ```bash
   cveta2 whats-new -p "Retail shelves" -d ~/data/old/dataset.csv
   ```

   Команда сравнивает проект с точкой отсчёта whats-new ([what's-new baseline](../GLOSSARY.md)) и печатает завершённые задачи, которых нет в прошлой выгрузке, например `id=456 shelves-batch-07 (updated ...)`. Если ничего нового нет, печатается `Новых завершённых задач ... не найдено`. Держите рядом с `dataset.csv` остальные три файла: иначе задачи из них будут показаны как новые. Подробнее — [whats-new](commands/whats-new.md).

2. Сделайте новую полную выгрузку в отдельный каталог:

   ```bash
   cveta2 fetch -p "Retail shelves" -o output/new/
   ```

   Неизменённые задачи берутся из кэша аннотаций, поэтому повторная выгрузка быстрее первой.

3. Объедините старый датасет с новым:

   ```bash
   cveta2 merge --old ~/data/old/dataset-split.csv --new output/new/dataset.csv \
     --deleted output/new/deleted.csv --in-progress output/new/in_progress.csv \
     -o ~/data/merged.csv
   ```

   Изображение берётся целиком из одного файла; при конфликте побеждает `--new`. Split переносится из старого файла, поэтому изображения не переходят из train в test. Удалённые изображения ([deleted image](../GLOSSARY.md)) из `--deleted` убираются из обоих файлов, изображения с переоткрытым удалением ([reopened deletion](../GLOSSARY.md)) из `--in-progress` — только из `--old`. В конце печатается итог, например `Результат слияния: только в old=0, только в new=4, конфликт→new=8, ...`. Подробнее — [merge](commands/merge.md).

4. У новых изображений split пустой. Назначьте его тем же скриптом из сценария 1: он не трогает уже заполненный split.

   ```bash
   python assign_split.py ~/data/merged.csv ~/data/merged-split.csv
   cveta2 convert --to-yolo -d ~/data/merged-split.csv -o output/yolo-v2 --image-dir ~/data/images
   ```

## 3. Цикл предразметки

Модель сделала предсказания в формате YOLO, а аннотаторы должны их исправить в CVAT.

1. Положите файлы предсказаний `.txt` (по одному на изображение, имя файла как у изображения) в `output/predictions/` и опишите классы в `~/data/names.yaml`:

   ```yaml
   names:
     0: bottle
     1: can
   ```

   Имена классов должны совпадать с метками (label) проекта. Список меток показывает `cveta2 labels -p "Retail shelves" --list` ([labels](commands/labels.md)).

2. Переведите предсказания в CSV:

   ```bash
   cveta2 convert --from-yolo -i output/predictions -o output/predictions.csv \
     --names-file ~/data/names.yaml --image-dir ~/data/images/"Retail shelves"
   ```

   Изображения ищутся только прямо в каталоге `--image-dir` и в его подкаталоге `images`, поэтому укажите каталог, где файлы лежат прямо, а не корень кэша. Размер читается из заголовка каждого изображения. Если для файла предсказаний не найдено изображение, команда завершается с ошибкой `Ошибка: не найдены изображения для N файлов: ...` и не пишет CSV. Подробнее — [convert](commands/convert.md#--from-yolo).

3. Создайте задачу в CVAT:

   ```bash
   cveta2 upload -p "Retail shelves" -d output/predictions.csv --labels all \
     --name "shelves-preannot-01" --image-dir ~/data/images/"Retail shelves"
   ```

   Команда загружает в S3 изображения, которых там нет, создаёт задачу, переносит bbox и печатает `Задача создана: id=456, ...` и ссылку на задачу. Каждый успешный запуск создаёт новую задачу: не запускайте команду второй раз. Если загрузка оборвалась, повторите ту же команду с `--resume` (возобновление загрузки, [upload resume](../GLOSSARY.md)). Подробнее — [upload](commands/upload.md).

4. Аннотаторы исправляют разметку в CVAT и завершают задачу: все job на stage `acceptance` со state `completed`. Если это нужно сделать без интерфейса CVAT:

   ```bash
   cveta2 task status -p "Retail shelves" -t 456 --stage acceptance --state completed
   ```

5. Выгрузите исправленную задачу:

   ```bash
   cveta2 fetch-task -p "Retail shelves" -t 456 -o output/reviewed/
   ```

   Выгрузка задач ([task fetch](../GLOSSARY.md)) пишет только `dataset.csv` и `deleted.csv`. Завершённая задача также попадёт в следующую полную выгрузку проекта, как любая другая. Подробнее — [fetch-task](commands/fetch-task.md).

6. Уберите то, что не должно попасть в датасет.

   - Неудачные кадры (frame) пометьте удалёнными, а все аннотации лишней метки удалите из задачи (метка в проекте остаётся):

     ```bash
     cveta2 task mark-deleted -p "Retail shelves" -t 456 --frame 0 --image shelf_0025.jpg
     cveta2 task drop-label -p "Retail shelves" -t 456 --label can --yes
     ```

   - Задачу, которую нужно оставить в CVAT, но не выгружать, добавьте в список игнорируемых задач ([ignore list](../GLOSSARY.md)):

     ```bash
     cveta2 ignore -p "Retail shelves" --add 456 -d "предразметка, не проверена"
     cveta2 ignore --list
     ```

     Список хранится в общей конфигурации, и проект должен быть в ней описан. Иначе команда печатает `... добавлена в ignore-список ...`, а затем ошибку `Unknown shared projects` и код `1`: список не сохранён. Подробнее — [ignore](commands/ignore.md).

   - Ненужную задачу удалите. Удаление нельзя отменить:

     ```bash
     cveta2 task delete -p "Retail shelves" -t 456 --yes
     cveta2 ignore -p "Retail shelves" --remove 456
     ```

     Вторая команда нужна, только если задача была в списке игнорируемых задач. Подробнее — [task](commands/task.md).

## 4. Публикация в ClearML

Есть два пути.

| | Ручная подготовка ([bundle preparation](../GLOSSARY.md)) | Управляемый датасет ([managed dataset](../GLOSSARY.md)) |
|---|---|---|
| Команды | `verify <каталог>`, `upload-dataset` | `dataset fetch`, `prepare`, `report-errors`, `publish` |
| Что нужно в общей конфигурации | ничего; настройки публикации проекта (`publication`) избавляют от флагов | запись в разделе `datasets` |
| Вход | каталог полной выгрузки одного проекта | источники ([source](../GLOSSARY.md)) датасета: проекты CVAT и CSV в S3 |
| Классы, корни изображений | из настроек публикации проекта (черновик `dataset.yaml`) или флагов `verify` | из общей конфигурации |
| split | назначаете вы; опубликованное изображение сохраняет свой split ([stable split](../GLOSSARY.md)): `verify` заполняет его из родителя, `upload-dataset` не даёт изменить без `--force-resplit` | назначаете вы; опубликованное изображение сохраняет свой split ([stable split](../GLOSSARY.md)): `dataset prepare` переносит его из родителя, `dataset publish` не даёт изменить без `--force-resplit` |
| Замечания в CVAT | нет | замечания к кадрам ([feedback finding](../GLOSSARY.md)) как issue |

Выбирайте управляемый датасет, если команда описала его в разделе `datasets` общей конфигурации: все, кто его публикует, работают с одними и теми же источниками, классами и split. Ручная подготовка подходит, когда записи нет, а вам нужно опубликовать одну выгрузку проекта.

### Ручная подготовка

1. Один раз опишите настройки публикации проекта в общей конфигурации. Это делает тот, кто ведёт общий файл:

   ```bash
   cveta2 setup --global --project "Retail shelves" --clearml-project Retail/Datasets \
     --dataset-name retail-shelves --api-url https://classes.example.com/api
   ```

   Подробнее — [setup](commands/setup.md). Без этих настроек всё работает так же, но значения придётся передавать флагами `verify` или вписывать в черновик.

2. Сделайте полную выгрузку:

   ```bash
   cveta2 fetch -p "Retail shelves" -o out/fetch
   ```

   Рядом с четырьмя CSV появится черновик `dataset.yaml`: назначение в ClearML, API классов, исключённые классы и корни изображений из настроек публикации проекта. Если чего-то не хватает, `fetch` печатает предупреждение и подсказку, но не завершается с ошибкой. Черновик можно поправить. Подробнее — [Черновик dataset.yaml](commands/fetch.md#черновик-datasetyaml).

3. Подготовьте датасет:

   ```bash
   cveta2 verify out/fetch
   ```

   Команда читает черновик, ищет родительский датасет в ClearML, сверяет классы с API, проверяет каждое изображение и пишет подготовленный датасет в `out/fetch-prepared` (если он занят — в `out/fetch-prepared-2` и так далее). Отклонённые строки не попадают в набор: команда печатает их число, а строки изображений с отклонёнными строками пишет в `broken-images.csv`. Последние строки вывода:

   ```text
   Набор подготовлен: /home/user/out/fetch-prepared
   Перед публикацией: заполните split у 120 изображений в /home/user/out/fetch-prepared/dataset.csv
   Затем: cveta2 upload-dataset /home/user/out/fetch-prepared
   ```

   Код завершения `0`. Если набор не подготовлен (например, у неисключённого класса нет ни одного bbox), команда печатает причины, `Набор не подготовлен; отчёт: …/report.json` и завершается с кодом `1`. Состав каталога — [Подготовленный датасет](dataset-format.md#подготовленный-датасет), флаги и правила — [verify](commands/verify.md#подготовка-каталога).

4. Заполните оставшиеся пустые `split` в `out/fetch-prepared/dataset.csv`. Изображения, уже опубликованные в родителе, получили свой split от `verify`; скрипт из сценария 1 заполняет только пустые ячейки:

   ```bash
   python assign_split.py out/fetch-prepared/dataset.csv out/fetch-prepared/dataset.csv
   ```

   Просмотрите `report.json`, `broken-images.csv` и `dataset.yaml`. Файлы каталога можно править: `upload-dataset` проверяет их такими, какие они есть.

5. Опубликуйте:

   ```bash
   cveta2 upload-dataset out/fetch-prepared
   ```

   Команда заново проверяет файлы каталога, загружает новую версию и печатает `Опубликован датасет <id>, версия 1.0.0.` Если вы изменили split изображения, уже опубликованного в родителе, публикация останавливается; `--force-resplit` разрешает это явно. Публикацию ([publication](../GLOSSARY.md)) нельзя отменить. Подробнее — [upload-dataset](commands/upload-dataset.md).

### Управляемый датасет

Пусть в общей конфигурации описан датасет `shelves-det` ([как его описать](commands/dataset.md#описание-датасета-в-общей-конфигурации)). `cveta2 dataset list` печатает все такие записи.

1. Выгрузите источники:

   ```bash
   cveta2 dataset fetch shelves-det --output-dir output/fetch
   ```

   В `output/fetch` появятся `dataset.csv`, `sources/` и `source-snapshot.yaml` (снимок источников, [source snapshot](../GLOSSARY.md)). Результат печатается в JSON: число строк и номера задач каждого источника.

2. Преобразуйте `dataset.csv` своим кодом и сохраните результат в отдельный файл. Обязательно заполните `image_path`: после `dataset fetch` он пустой. Пример ищет файл каждого изображения в кэше по имени:

   ```python
   # transform.py
   import sys
   from pathlib import Path

   import pandas as pd

   src, images_dir, dst = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
   df = pd.read_csv(src)

   paths = {p.name: str(p.resolve()) for p in images_dir.rglob("*") if p.is_file()}
   df["image_path"] = df["image_name"].map(paths)

   # Split новых изображений назначаете вы — правило здесь только пример.
   # У изображений, уже опубликованных в родительской версии, cveta2 запишет опубликованный split.
   names = sorted(df["image_name"].unique())
   df["split"] = df["image_name"].map({name: "val" if i % 5 == 0 else "train" for i, name in enumerate(names)})

   df.to_csv(dst, index=False)
   print("без файла:", df["image_path"].isna().sum())
   ```

   ```bash
   python transform.py output/fetch/dataset.csv ~/data/images output/transformed.csv
   ```

   Если в кэше два файла с одним именем, пример возьмёт любой из них: в своём коде выбирайте путь точнее. Здесь же можно выбрать строки или поправить классы. Требования к CSV — [prepare](commands/dataset.md#что-должен-содержать-преобразованный-csv).

3. Подготовьте датасет:

   ```bash
   cveta2 dataset prepare shelves-det output/transformed.csv --source output/fetch \
     --output-dir output/prepared
   ```

   Управляемая подготовка ([managed preparation](../GLOSSARY.md)) переносит опубликованный split на уже опубликованные изображения; split новых изображений заполняете вы в преобразованном CSV. Отклонённые строки очистка удаляет по умолчанию. В JSON смотрите `"ready"`: `true` и код `0` — каталог записан; `false` и код `1` — причины в `"blockers"` (например, класс без bbox или одно изображение в нескольких split). В `"pending"` — условия split, которые потребует `publish`: заполните split новых изображений в `output/prepared/dataset.csv`, если он пуст. Подробнее — [prepare](commands/dataset.md#prepare).

   После `prepare` можно поправить `output/prepared/dataset.csv` и `dataset.yaml`, например убрать строки изображения. Контрольных сумм нет: `report-errors` и `publish` проверяют файлы такими, какие они сейчас, и `publish` опубликует правку, если она проходит проверки.

   Если в `clearml.dataset` ещё нет версий, это будет первая версия управляемой истории. Если там уже есть версии, опубликованные не через `dataset publish` (например, через `upload-dataset`), `prepare` остановится с `Parent <id> is not a managed dataset version; start a managed lineage with dataset prepare --first`. Тогда подготовьте первую управляемую версию с флагом `--first`: весь split возьмётся из вашего CSV, а `publish` создаст версию без родителя. Следующие подготовки делайте без флага.

4. Отправьте замечания к кадрам в CVAT:

   ```bash
   cveta2 dataset report-errors output/prepared
   ```

   JSON показывает, сколько issue создано (`created`), сколько уже было (`existing`), какие не доставлены (`failed`) и сколько пропущено, потому что их задачи изменились после `fetch` (`skipped`). Шаг можно пропустить: `publish` доставит замечания сам. Подробнее — [report-errors](commands/dataset.md#report-errors).

5. Опубликуйте:

   ```bash
   cveta2 dataset publish output/prepared
   ```

   Команда проверяет текущие файлы подготовки и источники, пересчитывает служебные данные (назначения split в `dataset.yaml`, `tasks.yaml`) из текущего `dataset.csv` и печатает `{"dataset_id": "...", "version": "1.0.0"}`. Опубликованное изображение сохраняет свой split: чтобы перенести его в другой split, запустите `publish` с `--force-resplit`. Одно изображение в нескольких split не публикуется никогда. Номер версии назначает ClearML, например следующая публикация того же датасета получает `1.0.1`. Из изменений в CVAT, S3 и ClearML публикацию останавливают задача CVAT, завершённая после `fetch`, и новая версия в ClearML: повторите шаги с `dataset fetch`. Остальные изменения источников (задачу правили, переоткрыли или удалили, изменились метки проекта, в S3 лежит другой CSV-объект) только печатают предупреждения: датасет публикуется из выгруженных данных, а замечания к таким задачам не отправляются и считаются. Подробнее — [publish](commands/dataset.md#publish).

6. Сравните две версии: по ID в ClearML (их печатает `cveta2 dataset versions shelves-det`) или два локальных каталога подготовки:

   ```bash
   cveta2 dataset diff 1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6 7f6e5d4c3b2a41908f7e6d5c4b3a2910
   cveta2 dataset diff output/prepared-v1 output/prepared-v2
   ```

   JSON показывает изменения строк, изображений, классов и число изображений в каждом split. Подробнее — [diff](commands/dataset.md#diff).

## См. также

- [Указатель документации](README.md)
- [Формат данных](dataset-format.md)
- [Конфигурация](configuration.md)
- [Изображения и кэши](images-and-cache.md)
- [Python API](python-api.md)
- [Глоссарий](../GLOSSARY.md)

# Участие в разработке

## Быстрый старт

```bash
git clone <repo-url>
cd cveta2
uv sync
uv run pre-commit install   # хуки commit, commit-msg и pre-push разом
git config core.sshCommand "ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=40"
```

Одной команды достаточно: список стадий задан в `.pre-commit-config.yaml`
(`default_install_hook_types`).

Последняя строка нужна для пуша: git открывает SSH-соединение с GitHub **до**
запуска pre-push-хуков, а гейты идут дольше, чем GitHub держит простаивающую
сессию. Без keepalive пуш заканчивается сообщением
`Connection to github.com closed by remote host` уже после того, как все
хуки прошли, и на сервер ничего не попадает. Настройка локальная для этого
клона и никак не влияет на другие репозитории; подробнее — в «Ветки и релизы».

Требования: Python 3.10+ (пакет), [uv](https://docs.astral.sh/uv/),
Docker + Compose v2 (только для интеграционных тестов).

Версии Python в проекте различаются намеренно: `requires-python = ">=3.10"` —
это floor **пакета**; `.python-version` пинит **разработку** на 3.12; mypy
анализирует как 3.11 (floor установленных зависимостей, см. ниже). Ставить
везде одно число не нужно и вредно.

Сабмодулей у репозитория нет: `docker-compose.yml` для стека CVAT
`integration_up.sh` скачивает сам (см. «Интеграционные тесты»).

## Стиль кода

- **Логирование** — только `loguru`, никогда `print`. Используйте f-строки, а не структурированный вывод loguru.
- **Конфигурации** — всегда через Pydantic-модели.
- **Типы вместо строк** — `Literal`, `Enum`, typed dataclass. Не используйте строки там, где можно задать тип.
- **Не используйте** `getattr` / `hasattr` / `__dict__` (единственное исключение — `cvat_sdk`, где SDK-объекты непрозрачны; обязателен комментарий с объяснением).
- **Комментарии** — только для неочевидной логики. Не дублируйте код словами, не описывайте «что» делает код — только «почему».
- **Docstrings** — обязательны для публичных функций и классов (контролируется ruff).

## Инструменты качества кода

Вся конфигурация линтеров — в `pyproject.toml`. Все инструменты запускаются через `uv run`.

### Запуск всего сразу

Хуки установлены, поэтому `git commit` сам прогоняет весь набор.
Незакоммиченные изменения на время прогона убираются в stash, так что
проверяется ровно то, что коммитится. Если хук переписал файлы
(`ruff format`, `uv lock`), коммит прерывается: добавьте изменения в индекс и
повторите.

Прогнать всё вручную, не коммитя:

```bash
uv run pre-commit run --all-files
```

Pre-commit запускает хуки в следующем порядке:

1. `ruff format` — форматирование
1. `ruff check` — линтинг
1. `lint-imports` — проверка архитектурных контрактов
1. `mypy` — статическая типизация
1. `vulture` — поиск мёртвого кода
1. `pytest` — тесты
1. `mutmut` — мутационное тестирование
1. `count-lines` — подсчёт строк кода
1. `uv build` — проверка собираемости пакета
1. `uv lock` — синхронизация lock-файла

Всегда запускайте `ruff format` перед `ruff check` — форматтер может создать/исправить lint-ошибки.

На стадии `commit-msg` работает `conventional-commit`: он не пропускает
заголовок, который не разберёт semantic-release, и `!` без футера
`BREAKING CHANGE:`. Заголовки `Merge …`, `Revert …` и autosquash он не трогает.

На стадии `pre-push` — три хука подряд: `mutmut-full` (весь охват мутационного
тестирования), `version-drift` (поле `version` должно совпадать с ближайшим
тегом, чтобы правка руками не доехала до `main`) и `integration-tests`
(см. «Интеграционные тесты»).

### ruff format (форматирование)

```bash
uv run ruff format .          # отформатировать всё
uv run ruff format --check .  # проверка без изменений (exits non-zero если есть неотформатированное)
```

Конфигурация:

- `line-length = 88`
- `target-version = "py310"`
- `docstring-code-format = true` — форматирует примеры кода в docstrings
- Директория `scripts/` форматируется, но **не линтуется**
- Директория `vendor/` исключена полностью (остаётся от старых клонов с сабмодулем CVAT)

### ruff check (линтинг)

```bash
uv run ruff check .        # проверить
uv run ruff check --fix .  # автоматически исправить безопасные нарушения
```

Конфигурация:

- `select = ["ALL"]` — включены **все** правила ruff
- Отключённые правила:

| Правило | Причина отключения |
|---|---|
| `COM812` | Конфликтует с ruff formatter (missing-trailing-comma) |
| `ISC001` | Конфликтует с formatter (single-line-implicit-string-concatenation) |
| `EM` | Избыточно для небольших проектов (flake8-errmsg) |
| `TRY003` | Аналогично EM (raise-vanilla-args) |
| `D213` | Конфликт стилей docstring (multi-line-summary-second-line) |
| `D203` | Конфликт стилей docstring (one-blank-line-before-class) |
| `RUF001` | Проект использует кириллицу (ambiguous-unicode-character) |
| `PERF203` | Ложные срабатывания в Python 3.11+ (try-except-in-loop) |
| `CPY001` | Проект не использует per-file copyright-заголовки |

`PLR2004` (magic value comparison) включён для `cveta2/`: числовой литерал
в сравнении выносится в константу уровня модуля. Побочный эффект — такие
константы не мутируются mutmut (мутируется только код внутри функций), так
что вынос литерала убирает и группу неубиваемых мутантов.

- Per-file overrides:
  - `tests/**` — отключены `S101` (assert), `S105`/`S106` (hardcoded password),
    `ANN401` (`Any` в аннотациях), `PLR2004`, `PLC0415` (import not at top),
    `D101`/`D102`/`D103` (missing docstrings), `S311` (random),
    `SLF001` (доступ к приватным атрибутам)
  - `scripts/*.py` — отключены `T201` (`print` — это их вывод), `D103`,
    `ANN401`, `PLR2004`, `S607`, и правила «слишком длинная функция»
    (`C901`, `PLR0912`, `PLR0915`, `PLR0913`, `PLR0917`): argparse-`main()`
    в утилите линеен сверху вниз

### mypy (статическая типизация)

```bash
uv run mypy .
```

Конфигурация:

- `strict = true` — строжайший режим
- `python_version = "3.11"` — это floor *установленных зависимостей*, а не
  `requires-python`. На 3.10 pandas-stubs 3.0 деградирует `DataFrame` до
  `Any` и проверка типов pandas молча выключается целиком
- `warn_return_any = true`
- `warn_unused_configs = true`
- Исключены: `vendor/` (ради старых клонов с сабмодулем CVAT), `local/` и
  `mutants/` (копия дерева от mutmut — иначе mypy видит два пакета `cveta2`
  и падает с duplicate-module). `scripts/` **не** исключена
- Для `cvat_sdk.*` установлено `ignore_missing_imports = true` (SDK не поставляет полные стабы)
- Type stubs для сторонних библиотек в dev-зависимостях: `boto3-stubs`, `pandas-stubs`, `types-tqdm`, `types-pyyaml`

### import-linter (архитектурные контракты)

```bash
uv run lint-imports
```

Четыре контракта, определённых в `pyproject.toml`:

**1. Слои архитектуры** (тип `layers`):

```
cli → commands → api → services → _clearml → client → _client_ops → _client
```

Импорты допускаются только сверху вниз. Нижние слои не могут импортировать верхние. Доменные типы (`TaskInfo`, `LabelInfo`, `ProjectInfo`) живут в `models.py` (фундаментный слой) и импортируются всеми слоями без нарушений.

**2. Изоляция фундаментных модулей** (тип `forbidden`):

Модули `models` и `exceptions` **не могут** импортировать из: `client`, `api`, `services`, `commands`, `cli`, `_client`.

**3. Изоляция конфигурации** (тип `forbidden`):

Модуль `config` **не может** импортировать из: `client`, `api`, `services`, `commands`, `cli`, `_client`, `models`. Может зависеть только от `exceptions`.

**4. Изоляция слоя ClearML** (тип `forbidden`):

Пакет `_clearml` **не может** импортировать из: `client`, `commands`, `cli`, `_client`, `models`.

При добавлении новых модулей или кросс-модульных импортов запускайте `uv run lint-imports`.

### vulture (мёртвый код)

```bash
uv run vulture
```

- `min_confidence = 80`
- Сканирует `cveta2/` и `main.py`
- Если vulture помечает используемый код (например, публичный API), добавьте whitelist-запись или повысьте confidence

### pytest (тесты)

```bash
uv run pytest              # параллельно (по умолчанию)
uv run pytest -x           # остановиться на первой ошибке
uv run pytest -n0          # в один поток (для отладки)
uv run pytest -k "test_labels"  # запустить по имени
```

- `-v --tb=short -n auto -p tests.env_isolation` — настройки по умолчанию из
  `pyproject.toml`; последний плагин изолирует переменные окружения
- `-n auto` включает параллельное выполнение через `pytest-xdist`
- Интеграционные тесты запускаются только при наличии `CVAT_INTEGRATION_HOST`

### mutmut (мутационное тестирование)

```bash
./scripts/mutation_test.sh --profile fast        # подмножество для pre-commit
./scripts/mutation_test.sh --profile full        # весь охват, запускается на pre-push
./scripts/mutation_test.sh 'cveta2.dataset_partition.*'  # один модуль
uv run mutmut show <имя-мутанта>                 # diff конкретного мутанта
uv run mutmut browse                             # интерактивный разбор
```

Проверяет, что тесты действительно *проверяют* поведение, а не просто
исполняют код, и падает, если выжил хоть один мутант без объяснения.

Полный гейт живёт в хуке pre-push — его ставит общий `uv run pre-commit install`.

- Охват задаётся в `[tool.mutmut].only_mutate`; счёт мутантов и score печатает
  сам `mutation_test.sh`. Каждый модуль оттуда стоит на нуле *необъяснённых*
  выживших. Новый модуль в `cveta2/` добавляйте в `only_mutate` тем же
  коммитом, который доводит его до нуля выживших, чтобы гейт на `main` никогда
  не был красным. Критерий
  простой: бизнес-логика идёт в ратчет, а адаптеры, модули без изменяемой
  поверхности и обвязка остаются вне гейта навсегда. Полный список и
  обоснования — в разделе «Permanently out of scope»
  файла `.claude/skills/mutation-testing/SKILL.md`.
- Если хук упал — по умолчанию усильте тест. Если мутация в принципе не может
  изменить поведение, добавьте её в `[tool.cveta2.mutation.equivalent]` в
  `pyproject.toml` с обоснованием.
- **Не перестраивайте рабочий код ради гейта.** Вынести подпись прогресс-бара
  в константу уровня модуля действительно убирает мутанта (mutmut мутирует
  только код внутри функций), но это зелёный гейт ценой худшего кода, и
  стоимость этой косвенности платит каждая следующая фича. Презентационные
  вызовы (`logger.*`, `tqdm(...)`, `sys.exit(...)`) исключены глобально
  паттернами в `[tool.mutmut].do_not_mutate_patterns` — если появилась новая
  такая поверхность, добавьте её туда, а не прячьте литерал.
- Гейт падает и на «протухшей» записи allowlist: mutmut перенумеровывает
  мутантов при изменении функции, поэтому обоснование не может незаметно
  переехать на другого мутанта.
- Рабочая копия mutmut лежит в `mutants/` — каталог в `.gitignore` и исключён
  из mypy и ruff. `only_mutate` и `do_not_mutate_patterns` не входят в
  собственный «отпечаток» конфига mutmut, поэтому после их изменения дерево
  мутантов устаревает; `mutation_test.sh` сам это отслеживает и пересобирает
  `mutants/`.

Подробности механики (что именно мутируется, почему декорированные функции и
константы уровня модуля не дают мутантов) —
в `.claude/skills/mutation-testing/mutation-internals.md`.

## Тесты

### Юнит-тесты

Внешние сервисы не нужны — тесты работают на JSON-фикстурах.

Покрытие:

- **merge** (`tests/test_merge.py`) — split propagation, default merge (new wins), by-task merge, I/O (CSV и legacy), CLI end-to-end
- **partition** (`tests/test_partition.py`) — разбиение на dataset/obsolete/in_progress
- **extractors** (`tests/test_extractors.py`) — конвертация shapes в BBoxAnnotation
- **image download** (`tests/test_image_downloader.py`) — S3 download, caching, S3Syncer
- **labels** (`tests/test_labels.py`) — add/rename/recolor/delete

### Фикстуры CVAT

Фикстуры лежат в `tests/fixtures/cvat/<project_name>/` (`project.json` и `tasks/*.json`). JSON-структура соответствует `_client/dtos.py`.

Чтобы пересоздать фикстуры из реального CVAT:

```bash
export CVAT_HOST="http://localhost:8080"
export CVAT_USERNAME="admin"
export CVAT_PASSWORD="ваш_пароль"
uv run python scripts/export_cvat_fixtures.py --project coco8-dev
```

По умолчанию вывод в `tests/fixtures/cvat/coco8-dev/`. Другой каталог: `--output-dir path`.

**Фейковые проекты** — для тестов можно собирать из базовых фикстур: произвольный набор задач, с повторами, случайными или заданными именами и статусами. Модуль `tests/fixtures/fake_cvat_project.py`: `FakeProjectConfig` (pydantic) и `build_fake_project(base_fixtures, config)`.

### Интеграционные тесты

Прогоняют тесты против живого CVAT + MinIO + ClearML. CVAT — постоянный стенд
в локальном Kubernetes-кластере (`http://cvat.k8s.localhost`, см. скилл
`k8s-infra`); скрипты его не поднимают и не гасят. MinIO и ClearML живут в
Docker Compose (`tests/integration/docker-compose.yml`) и пересоздаются на
каждый прогон.

```bash
# 1. Подготовить прогон: проверить стенд, поднять MinIO + ClearML, засеять проект
./scripts/integration_up.sh
./scripts/integration_up.sh --minio-port 9189   # если порт по умолчанию занят

# 2. Запустить тесты (скрипт сам выставляет env-переменные и отключает xdist)
./scripts/integration_test.sh
./scripts/integration_test.sh -k upload        # только upload-тесты
./scripts/integration_test.sh -x --tb=long     # остановиться на первой ошибке

# 3. Снести compose-стек и данные прогона в CVAT
./scripts/integration_stop.sh
```

Тесты ходят в CVAT под отдельным пользователем внутри одной организации
(по умолчанию `cveta2` и `cveta2-tests`); `integration_up.sh` регистрирует
обоих при первом запуске. Все объекты прогона в CVAT носят **тег прогона**:
проект `<тег> coco8-dev` и облачное хранилище `<тег> minio`. Тег выводит
`scripts/integration_env.sh` — на `main` это `INTEGRATION_USER` (по умолчанию
`$USER`), на любой другой ветке `INTEGRATION_USER-<ветка>`; переопределяется
через `INTEGRATION_RUN_TAG`. Тот же тег даёт имя compose-проекту
(`<тег>-cveta2`).

Перед засевом `integration_up.sh` удаляет из организации всё с этим тегом,
поэтому повторный прогон всегда начинается с чистого проекта — именно так
upload-тесты не встречают собственных остатков (`Duplicate base task name`).
Два одновременных прогона с одним тегом несовместимы: второй снесёт проект
первого. Параллельным агентам нужны разные `INTEGRATION_USER` и разные порты.

Управление аккаунтом и организацией — `tests/integration/cvat_stand.py`:

```bash
uv run python tests/integration/cvat_stand.py bootstrap             # пользователь, организация, доступность стенда
uv run python tests/integration/cvat_stand.py ls                    # что сейчас лежит в организации
uv run python tests/integration/cvat_stand.py cleanup --tag <тег>   # удалить объекты одного прогона
uv run python tests/integration/cvat_stand.py cleanup --stale 24 --dry-run   # сироты от погибших прогонов
```

Посмотреть данные прогона в интерфейсе стенда можно под `admin` стенда
(суперпользователь видит все организации) или под `cveta2` с паролем из `.env`.

Без `CVAT_INTEGRATION_HOST` интеграционные тесты не запускаются. Скрипт `integration_test.sh` выставляет эту переменную автоматически.

### Гейт на pre-push

`scripts/integration_gate.sh` (хук `integration-tests`) делает на пуше весь цикл
сам: готовит стек, гоняет `tests/integration`, а дальше смотрит на ветку.
Прогон с `main` (пуш `refs/heads/main` или `main` в рабочей копии) **остаётся**:
compose-стек и проект `<тег> coco8-dev` на стенде не удаляются, чтобы последний
прогон можно было открыть в интерфейсе CVAT; следующий прогон с `main` заменит
его. Прогон с любой другой ветки убирает за собой. `INTEGRATION_KEEP_DATA=1`
или `=0` переопределяет это решение.

Прогоняется только `tests/integration` — переменная `CVAT_INTEGRATION_HOST`
заодно добавляет параметр `live-cvat` в фикстуру `coco8_fixtures`, и юнит-тесты
пошли бы по живому CVAT ещё раз, последовательно. Такой прогон запускают руками:
`./scripts/integration_test.sh`.

Гейт включается сам по наличию `tests/integration/.env` — файл в `.gitignore`,
поэтому на свежем клоне и на любой другой машине интеграционных тестов на пуше
просто нет. Включить: `cp tests/integration/.env.example tests/integration/.env`
и заполнить пароль.

Два следствия, о которых лучше знать заранее:

- **Пуш пересоздаёт стек этого тега.** `integration_up.sh` всегда начинает с
  `docker compose down -v` и с удаления прошлого проекта тега в CVAT — свежее
  состояние здесь требование корректности.
- **Отсутствие `.env` — единственный тихий пропуск.** Если машина включена, а
  docker не поднят, стенд не отвечает или порт занят, гейт валит пуш, а не
  пропускает его.

Пропустить гейт на один пуш (`mutmut-full` при этом отработает):

```bash
SKIP=integration-tests git push
```

| Переменная | По умолчанию | Описание |
|---|---|---|
| `CVAT_INTEGRATION_HOST` | из `.env` | URL стенда CVAT; включает интеграционные тесты |
| `CVAT_INTEGRATION_USER` | из `.env` | Пользователь CVAT (регистрируется при первом запуске) |
| `CVAT_INTEGRATION_PASSWORD` | из `.env` | Его пароль |
| `CVAT_INTEGRATION_ORG` | из `.env` | Организация, в которой живут все объекты тестов |
| `CVAT_INTEGRATION_PROJECT` | `<тег> coco8-dev` | Полное имя засеянного проекта |
| `INTEGRATION_USER` | `$USER` | Префикс контейнеров и основа тега прогона |
| `INTEGRATION_RUN_TAG` | см. выше | Тег прогона, если нужно задать явно |
| `INTEGRATION_KEEP_DATA` | по ветке | `1` — оставить прогон после гейта, `0` — убрать |
| `MINIO_PORT`, `CLEARML_API_PORT`, … | `9989`, `8880`, … | Порты compose-стека |

## Ветки и релизы

Работа идёт в ветках, `main` меняется только вливанием — и версия появляется
не «когда накопится», а сразу: **каждое изменение `main` заканчивается релизом**.
Тег отстаёт от `main` ровно на время между вливанием и командой релиза.

```
feature-branch → правки, коммиты → влить в main → выпустить релиз с main
```

Ветку от `main` отводят под одно изменение и вливают целиком. Название произвольное,
но тип коммитов важен: именно из них считается версия (таблица ниже).

`semantic-release` сам откажется работать где-либо кроме `main`:

```
branch 'my-feature' isn't in any release groups; no release will be made
```

Это не ошибка конфигурации, а защита: релиз возможен только с `main`.

### Что попадает в версию

Версию, тег и `CHANGELOG.md` считает
[python-semantic-release](https://python-semantic-release.readthedocs.io/) по истории
conventional-коммитов. Поле `version` в `pyproject.toml` руками не правят — его
проставляет релиз, а хук `version-drift` на pre-push сверяет его с ближайшим тегом.
Формат заголовка проверяет хук `conventional-commit` на `commit-msg`.

| Коммит | Бамп версии |
|---|---|
| `fix:`, `perf:` | patch (`0.1.0` → `0.1.1`) |
| `feat:` | minor (`0.1.0` → `0.2.0`) |
| `feat!:` или футер `BREAKING CHANGE:` | тоже minor, пока проект на `0.x` |

`major_on_zero = false`: сам по себе `0.x` в `1.0.0` не превратится, это отдельное
решение (`uv run semantic-release version --major`).

В раздел «BREAKING CHANGES» changelog-а ломающее изменение попадёт только при футере
`BREAKING CHANGE: <описание>` в теле коммита. Одного `!` в заголовке хватает для расчёта
версии, но текста для changelog он не даёт. Коммиты типов `chore` и `style` в changelog
не попадают вовсе (`exclude_commit_patterns`).

### Как выпустить

Сразу после вливания ветки, находясь на `main`:

```bash
uv run semantic-release version --print                       # какая версия получится
uv run semantic-release version --no-push --no-vcs-release    # локальный релиз
git push origin main --follow-tags                            # коммит и тег одним пушем
```

Первая команда ничего не меняет. Вторая правит `version` в `pyproject.toml`,
перегенерирует `CHANGELOG.md`, обновляет запись версии в `uv.lock` (это `build_command`,
единственная его задача), затем делает коммит `chore(release): X.Y.Z` и аннотированный
тег `vX.Y.Z`.

Пакет релиз не собирает: артефакт всё равно некуда публиковать, а собираемость проверяет
`uv build` в pre-commit.

Если во влитой ветке были одни `chore` / `docs` / `test`, первая команда ответит
`No release will be made, X.Y.Z has already been released!` и завершится успешно —
выпускать нечего, тег остаётся прежним. Проверять всё равно нужно каждый раз: только так
видно, какой это случай.

Пуш вынесен в отдельную команду не для красоты: он поднимает pre-push-хуки (полный
профиль мутационного тестирования, `version-drift`, интеграционный гейт), а
semantic-release пушит ветку и тег двумя разными пушами — гейты отработали бы дважды.

Гейты занимают больше десяти минут, а SSH-соединение с GitHub git открывает
до их запуска: без keepalive сервер закрывает простаивающую сессию, и пуш
падает с `Connection to github.com closed by remote host` при зелёных хуках —
`origin/main` и тег остаются старыми. Поэтому `core.sshCommand` с
`ServerAliveInterval` из «Быстрого старта» обязателен, а после пуша через
гейты стоит убедиться, что он дошёл:

```bash
git ls-remote origin refs/heads/main refs/tags/vX.Y.Z
```

Повторный `git push` после такого обрыва безопасен: хуки просто отработают ещё
раз. Обрезать их через `SKIP=…` из-за этого не нужно.

`--no-vcs-release` отключает создание GitHub Release, поэтому токен не нужен. На PyPI
пакет не публикуется.

## Архитектура

- **API-абстракция** — весь доступ к CVAT через протокол `CvatApiPort`.
  В продакшне — `SdkCvatApiAdapter` (обёртка над `cvat_sdk`),
  в тестах — `FakeCvatApi` (JSON-фикстуры).
- **DTO** (`_client/dtos.py`) — frozen dataclasses для CVAT API. Модели
  (`models.py`) — Pydantic. Конфиги (`config.py`) — тоже Pydantic.
- **CLI** (`cli.py`) — тонкий argparse; логика в `commands/` (по модулю на команду).
- **Слои и фундамент** — см. контракты import-linter выше.

Подробная карта модулей и потоки данных (fetch / upload / convert, разрешение
`ORG/PROJECT`, обработка удалённых кадров) — в `ARCHITECTURE.md`.

## Документация

| Файл | Для кого | Язык |
|---|---|---|
| `README.md` | Пользователей — точка входа | Русский |
| `docs/cli.md` | Пользователей — команды CLI | Русский |
| `docs/configuration.md` | Пользователей — конфиг и окружение | Русский |
| `docs/images-and-cache.md` | Пользователей — S3, кэш, ClearML | Русский |
| `docs/python-api.md` | Пользователей — Python API | Русский |
| `CONTRIBUTING.md` | Разработчиков | Русский |
| `DATASET_FORMAT.md` | Пользователей — формат выходных CSV | Английский |
| `ARCHITECTURE.md` | Разработчиков — карта модулей и потоки данных | Английский |
| `CLAUDE.md` | Агентов и разработчиков | Английский |

Правило: пользовательская и контрибьюторская документация (`README.md`,
`CONTRIBUTING.md`, `docs/`) — на русском; документация для разработчиков и
агентов (`CLAUDE.md`, `ARCHITECTURE.md`, `DATASET_FORMAT.md`) — на английском.
`tests/test_docs.py` это проверяет.

Обновляйте `docs/` при изменении CLI или API — `tests/test_docs.py` падает,
если появилась недокументированная команда, флаг, переменная окружения или
поле конфига, если документированный Python-пример разошёлся с сигнатурой,
или если ссылка перестала резолвиться.

## Решение проблем

**Порт занят** — `./scripts/integration_up.sh --minio-port 9189` (ClearML — через `CLEARML_*_PORT`)

**Стенд CVAT не отвечает** — `uv run python tests/integration/cvat_stand.py bootstrap` скажет, чего не хватает; сам стенд описан в скилле `k8s-infra`

**MinIO или ClearML не стартуют** — проверьте логи:

```bash
docker compose -p "$(whoami)-cveta2" logs
```

**Тесты падают после изменения фикстур** — перезапустите `./scripts/integration_up.sh`

**Пуш падает на `integration-tests`** — не поднят docker или занят один из портов
стека. Поднимите docker / освободите порт либо пропустите гейт на этот пуш:
`SKIP=integration-tests git push`

**Пуш падает на `version-drift`** — `version` в `pyproject.toml` разошёлся с
ближайшим тегом. Верните значение, которое проставил релиз; если ветка старше
последнего релиза `main`, перебазируйте её на `main`.

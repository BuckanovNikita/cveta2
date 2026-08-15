# Участие в разработке

## Быстрый старт

```bash
git clone <repo-url>
cd cveta2
uv sync
uv run pre-commit install   # хуки commit, commit-msg и pre-push разом
```

Одной команды достаточно: список стадий задан в `.pre-commit-config.yaml`
(`default_install_hook_types`).

Требования: Python 3.12+, [uv](https://docs.astral.sh/uv/),
Docker + Compose v2 (только для интеграционных тестов).

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

Хуки установлены, поэтому `git commit` сам прогоняет весь набор — отдельно
запускать ничего не нужно. Незакоммиченные изменения на время прогона убираются
в stash, так что проверяется ровно то, что коммитится. Если хук переписал файлы
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
  - `tests/**` — отключены `S101` (assert), `S105` (hardcoded password), `PLR2004`, `PLC0415` (import not at top), `D102`/`D103` (missing docstrings), `S311` (random)
  - `main.py` — отключён `F401` (unused import, т.к. re-export)
- `scripts/**` полностью исключена из линтинга (но форматируется)

### mypy (статическая типизация)

```bash
uv run mypy .
```

Конфигурация:

- `strict = true` — строжайший режим
- `python_version = "3.10"`
- `warn_return_any = true`
- `warn_unused_configs = true`
- Исключены: `scripts/`, `vendor/` (второе — ради старых клонов с сабмодулем CVAT)
- Для `cvat_sdk.*` установлено `ignore_missing_imports = true` (SDK не поставляет полные стабы)
- Type stubs для сторонних библиотек в dev-зависимостях: `boto3-stubs`, `pandas-stubs`, `types-tqdm`, `types-pyyaml`

### import-linter (архитектурные контракты)

```bash
uv run lint-imports
```

Три контракта, определённых в `pyproject.toml`:

**1. Слои архитектуры** (тип `layers`):

```
cli → commands → client → _client
```

Импорты допускаются только сверху вниз. Нижние слои не могут импортировать верхние. Доменные типы (`TaskInfo`, `LabelInfo`, `ProjectInfo`) живут в `models.py` (фундаментный слой) и импортируются всеми слоями без нарушений.

**2. Изоляция фундаментных модулей** (тип `forbidden`):

Модули `models` и `exceptions` **не могут** импортировать из: `client`, `commands`, `cli`, `_client`.

**3. Изоляция конфигурации** (тип `forbidden`):

Модуль `config` **не может** импортировать из: `client`, `commands`, `cli`, `_client`, `models`. Может зависеть только от `exceptions`.

При добавлении новых модулей или кросс-модульных импортов запускайте `uv run lint-imports` для проверки.

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

- `-v --tb=short -n auto` — настройки по умолчанию из `pyproject.toml`
- `-n auto` включает параллельное выполнение через `pytest-xdist`
- Интеграционные тесты запускаются только при наличии `CVAT_INTEGRATION_HOST`

### mutmut (мутационное тестирование)

```bash
./scripts/mutation_test.sh --profile fast        # подмножество для pre-commit (~17 c)
./scripts/mutation_test.sh --profile full        # весь охват, запускается на pre-push (~70 c)
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
  не был красным. Вне гейта осознанно оставлен только `_client/sdk_adapter.py`
  (граница SDK, сначала нужно покрытие) — см. `.claude/skills/mutation-testing/SKILL.md`.
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

```bash
uv run pytest           # параллельно (по умолчанию)
uv run pytest -n0       # в один поток (для отладки)
```

Внешние сервисы не нужны — тесты работают на JSON-фикстурах.

Покрытие:

- **merge** (`tests/test_merge.py`) — split propagation, default merge (new wins), by-time merge, I/O (CSV и legacy), CLI end-to-end
- **partition** (`tests/test_partition.py`) — разбиение на dataset/obsolete/in_progress
- **extractors** (`tests/test_extractors.py`) — конвертация shapes в BBoxAnnotation
- **mapping** (`tests/test_mapping.py`) — маппинг label/attribute
- **pipeline** (`tests/test_pipeline_integration.py`) — полный цикл через FakeCvatApi + CvatClient
- **image download** (`tests/test_image_downloader.py`) — S3 download, caching, S3Syncer
- **labels** (`tests/test_labels.py` и в `test_pipeline_integration.py`) — add/rename/recolor/delete

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

Прогоняют тесты против живого CVAT + MinIO + ClearML.

```bash
# 1. Поднять стек (порт по умолчанию 9988, всегда с нуля)
./scripts/integration_up.sh
./scripts/integration_up.sh --port 9080        # конкретный порт
./scripts/integration_up.sh --cvat-version v2.26.0  # конкретная версия CVAT

# 2. Запустить тесты (скрипт сам выставляет env-переменные и отключает xdist)
./scripts/integration_test.sh
./scripts/integration_test.sh -k upload        # только upload-тесты
./scripts/integration_test.sh -x --tb=long     # остановиться на первой ошибке

# 3. Остановить и удалить volumes
./scripts/integration_stop.sh
```

Базовый compose-файл — это `docker-compose.yml` самого CVAT. `integration_up.sh`
скачивает его один раз на версию в `.cache/cvat/<версия>/` (каталог в `.gitignore`),
дальше стек поднимается без сети. `--cvat-version` задаёт и compose-файл, и теги
образов `cvat/*`. Если машина не имеет доступа к `raw.githubusercontent.com`,
укажите свою копию файла: `CVAT_COMPOSE_FILE=/path/to/docker-compose.yml`.

Останавливающий скрипт compose-файл не читает — он сносит стек по метке проекта,
поэтому работает при любой версии и без сети.

Без `CVAT_INTEGRATION_HOST` интеграционные тесты не запускаются. Скрипт `integration_test.sh` выставляет эту переменную автоматически.

### Гейт на pre-push

`scripts/integration_gate.sh` (хук `integration-tests`) делает на пуше весь цикл
сам: поднимает стек, гоняет `tests/integration`, гасит стек. Прогоняется только
`tests/integration` — переменная `CVAT_INTEGRATION_HOST` заодно добавляет
параметр `live-cvat` в фикстуру `coco8_fixtures`, и юнит-тесты пошли бы по
живому CVAT ещё раз, последовательно. Такой прогон запускают руками:
`./scripts/integration_test.sh`.

Гейт включается сам по наличию `tests/integration/.env` — файл в `.gitignore`,
поэтому на свежем клоне и на любой другой машине интеграционных тестов на пуше
просто нет. Включить: `cp tests/integration/.env.example tests/integration/.env`.

Два следствия, о которых лучше знать заранее:

- **Пуш сносит поднятый стек.** `integration_up.sh` всегда начинает с
  `docker compose down -v`, вместе с volumes — свежее состояние здесь требование
  корректности, иначе upload-тесты падают на `Duplicate base task name`.
- **Отсутствие `.env` — единственный тихий пропуск.** Если машина включена, а
  docker не поднят или порт занят, гейт валит пуш, а не пропускает его.

Пропустить гейт на один пуш (`mutmut-full` при этом отработает):

```bash
SKIP=integration-tests git push
```

| Переменная | По умолчанию | Описание |
|---|---|---|
| `CVAT_INTEGRATION_HOST` | — | URL CVAT; включает интеграционные тесты |
| `CVAT_INTEGRATION_USER` | `admin` | Пользователь CVAT |
| `CVAT_INTEGRATION_PASSWORD` | `admin` | Пароль CVAT |
| `CVAT_COMPOSE_FILE` | — | Локальный `docker-compose.yml` CVAT вместо скачивания |

## Ветки и релизы

Работа идёт в ветках, `main` меняется только вливанием. Прямых коммитов в `main` нет —
и версия появляется не «когда накопится», а сразу: **каждое изменение `main` заканчивается
релизом**. Тег отстаёт от `main` ровно на время между вливанием и командой релиза.

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

`--no-vcs-release` отключает создание GitHub Release, поэтому токен не нужен. На PyPI
пакет не публикуется.

## Архитектура

- **API-абстракция** — весь доступ к CVAT через протокол `CvatApiPort`.
  В продакшне — `SdkCvatApiAdapter` (обёртка над `cvat_sdk`),
  в тестах — `FakeCvatApi` (JSON-фикстуры).
- **DTO** (`_client/dtos.py`) — frozen dataclasses для CVAT API. Модели
  (`models.py`) — Pydantic. Конфиги (`config.py`) — тоже Pydantic.
- **CLI** (`cli.py`) — тонкий argparse; логика в `commands/` (по модулю на команду).
- **Слои** — `cli → commands → client → _client` (защищено import-linter, см. выше).
- **Фундамент** — `models` и `exceptions` не зависят от верхних слоёв; `config` зависит только от `exceptions`.

Подробная карта модулей и потоки данных (fetch / upload / convert, разрешение
`ORG/PROJECT`, обработка удалённых кадров) — в `ARCHITECTURE.md`.

## Документация

| Файл | Для кого | Язык |
|---|---|---|
| `README.md` | Пользователей | Русский |
| `CONTRIBUTING.md` | Разработчиков | Русский |
| `DATASET_FORMAT.md` | Пользователей — формат выходных CSV | Английский |
| `ARCHITECTURE.md` | Разработчиков — карта модулей и потоки данных | Английский |

Обновляйте `README.md` при изменении API.

## Решение проблем

**Порт занят** — `./scripts/integration_up.sh --port 9080`

**CVAT не стартует** — проверьте логи:

```bash
docker logs "$(whoami)-cvat_server"
```

**Не скачивается compose-файл CVAT** — задайте `CVAT_COMPOSE_FILE` с путём к локальной копии `docker-compose.yml` CVAT

**Тесты падают после изменения фикстур** — перезапустите `./scripts/integration_up.sh`

**Пуш падает на `integration-tests`** — не поднят docker или занят один из портов
стека. Поднимите docker / освободите порт либо пропустите гейт на этот пуш:
`SKIP=integration-tests git push`

**Пуш падает на `version-drift`** — `version` в `pyproject.toml` разошёлся с
ближайшим тегом. Верните значение, которое проставил релиз; если ветка старше
последнего релиза `main`, перебазируйте её на `main`.

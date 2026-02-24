# Участие в разработке

## Быстрый старт

```bash
git clone --recurse-submodules <repo-url>
cd cveta2
uv sync
uv run pre-commit install   # автоматические проверки перед коммитом
```

Требования: Python 3.12+, [uv](https://docs.astral.sh/uv/),
Docker + Compose v2 (только для интеграционных тестов).

Забыли `--recurse-submodules`? — `git submodule update --init`.

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

```bash
uv run pre-commit run --all-files
```

Pre-commit запускает хуки в следующем порядке:

1. `ruff format` — форматирование
2. `ruff check` — линтинг
3. `lint-imports` — проверка архитектурных контрактов
4. `mypy` — статическая типизация
5. `vulture` — поиск мёртвого кода
6. `pytest` — тесты
7. `count-lines` — подсчёт строк кода
8. `uv build` — проверка собираемости пакета
9. `uv lock` — синхронизация lock-файла

Всегда запускайте `ruff format` перед `ruff check` — форматтер может создать/исправить lint-ошибки.

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
- Директория `vendor/` исключена полностью

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
| `PLR2004` | Magic value comparison — отключено глобально |

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
- Исключены: `scripts/`, `vendor/`
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

Прогоняют тесты против живого CVAT + MinIO.

```bash
# 1. Поднять CVAT + MinIO (всегда с нуля)
./scripts/integration_up.sh                    # случайный свободный порт
./scripts/integration_up.sh --port 9080        # конкретный порт
./scripts/integration_up.sh --cvat-version v2.26.0  # конкретная версия

# 2. Запустить тесты (порт — из вывода скрипта)
CVAT_INTEGRATION_HOST=http://localhost:<порт> uv run pytest

# 3. Остановить
docker compose --project-directory vendor/cvat \
  -f vendor/cvat/docker-compose.yml \
  -f tests/integration/docker-compose.override.yml \
  --env-file tests/integration/.env \
  down -v
```

Без `CVAT_INTEGRATION_HOST` интеграционные тесты не запускаются.

| Переменная | По умолчанию | Описание |
|---|---|---|
| `CVAT_INTEGRATION_HOST` | — | URL CVAT; включает интеграционные тесты |
| `CVAT_INTEGRATION_USER` | `admin` | Пользователь CVAT |
| `CVAT_INTEGRATION_PASSWORD` | `admin` | Пароль CVAT |

## Архитектура

- **API-абстракция** — весь доступ к CVAT через протокол `CvatApiPort`.
  В продакшне — `SdkCvatApiAdapter` (обёртка над `cvat_sdk`),
  в тестах — `FakeCvatApi` (JSON-фикстуры).
- **DTO** (`_client/dtos.py`) — frozen dataclasses для CVAT API. Модели
  (`models.py`) — Pydantic. Конфиги (`config.py`) — тоже Pydantic.
- **CLI** (`cli.py`) — тонкий argparse; логика в `commands/` (по модулю на команду).
- **Слои** — `cli → commands → client → _client` (защищено import-linter, см. выше).
- **Фундамент** — `models` и `exceptions` не зависят от верхних слоёв; `config` зависит только от `exceptions`.

## Документация

| Файл | Для кого | Язык |
|---|---|---|
| `README.md` | Пользователей | Русский |
| `CONTRIBUTING.md` | Разработчиков | Русский |
| `AGENT_DOCS.md` | AI-агентов и разработчиков — внутренние решения | Английский |
| `DATASET_FORMAT.md` | Пользователей — формат выходных CSV | Русский |

Обновляйте `README.md` и `AGENT_DOCS.md` при изменении API.

## Решение проблем

**Порт занят** — `./scripts/integration_up.sh --port 9080`

**CVAT не стартует** — проверьте логи:

```bash
docker compose --project-directory vendor/cvat \
  -f vendor/cvat/docker-compose.yml \
  -f tests/integration/docker-compose.override.yml \
  --env-file tests/integration/.env \
  logs cvat_server
```

**Ошибка про сабмодуль** — `git submodule update --init`

**Тесты падают после изменения фикстур** — перезапустите `./scripts/integration_up.sh`

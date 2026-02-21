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

- Логирование — только **loguru**, никогда `print`. Используйте f-строки.
- Конфигурации — всегда через **Pydantic**-модели.
- Типы вместо строк — `Literal`, `Enum`, typed dataclass.
- Не используйте `getattr` / `hasattr` / `__dict__` (исключение — `cvat_sdk`, с комментарием).
- Комментарии — только для неочевидной логики. Не дублируйте код словами.

## Инструменты

Вся конфигурация — в `pyproject.toml`. Подробности смотрите там.

| Инструмент | Что делает | Запуск вручную |
|---|---|---|
| **ruff** | Форматирование + линтинг (`select = ["ALL"]`) | `uv run ruff format .` / `uv run ruff check . --fix` |
| **mypy** | Статическая типизация (`strict = true`) | `uv run mypy .` |
| **vulture** | Поиск мёртвого кода | `uv run vulture` |
| **pytest** | Тесты (параллельно, `-n auto`) | `uv run pytest` |
| **pre-commit** | Всё вышеперечисленное + сборка + lock | `uv run pre-commit run --all-files` |

Pre-commit запускает по порядку: ruff format → ruff check → mypy → vulture →
pytest → count-lines → uv build → uv lock.

## Тесты

### Юнит-тесты

```bash
uv run pytest           # параллельно (по умолчанию)
uv run pytest -n0       # в один поток (для отладки)
```

Внешние сервисы не нужны — тесты работают на JSON-фикстурах.

### Интеграционные тесты

Прогоняют те же тесты против живого CVAT + end-to-end через SDK.

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

## Архитектура (кратко)

- **API-абстракция** — весь доступ к CVAT через протокол `CvatApiPort`.
  В продакшне — `SdkCvatApiAdapter` (обёртка над `cvat_sdk`),
  в тестах — `FakeCvatApi` (JSON-фикстуры).
- **DTO** (`_client/dtos.py`) — frozen dataclasses для CVAT API. Модели
  (`models.py`) — Pydantic. Конфиги (`config.py`) — тоже Pydantic.
- **CLI** (`cli.py`) — тонкий argparse; логика в `commands/` (по модулю на команду).

## Документация

| Файл | Для кого | Язык |
|---|---|---|
| `README.md` | Пользователей | Русский |
| `CONTRIBUTING.md` | Разработчиков | Русский |
| `AGENT_DOCS.md` | AI-агентов и разработчиков — внутренние решения | Английский |

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
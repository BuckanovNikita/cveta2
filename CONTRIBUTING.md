# Участие в разработке

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — менеджер пакетов
- Docker и Docker Compose v2 (для интеграционных тестов)

## Установка

```bash
git clone --recurse-submodules <repo-url>
cd cveta2
uv sync
```

Если репозиторий уже склонирован без `--recurse-submodules`:

```bash
git submodule update --init
```

## Запуск тестов

### Юнит-тесты (по умолчанию)

```bash
uv run pytest
```

Тесты запускаются **параллельно** (`-n auto` через `pytest-xdist`).
Количество воркеров определяется автоматически по числу ядер CPU.
Внешние сервисы не требуются.

Чтобы запустить тесты в один поток (например, для отладки):

```bash
uv run pytest -n0
```

### Интеграционные тесты

Интеграционные тесты прогоняют тот же набор тестов против живого
экземпляра CVAT (в дополнение к JSON-фикстурам) и включают
end-to-end тесты, использующие реальные вызовы CVAT SDK.

#### 1. Запуск CVAT + MinIO

```bash
./scripts/integration_up.sh
```

Скрипт всегда пересоздаёт CVAT с нуля:
- Останавливает и удаляет существующий стек (`docker compose down -v`)
- Скачивает изображения датасета coco8 (если ещё не скачаны)
- Запускает **минимальный** набор контейнеров (8 вместо ~19):
  `cvat_server`, `cvat_db`, `cvat_redis_inmem`, `cvat_redis_ondisk`,
  `cvat_opa`, `cvat_worker_import`, `cvat_worker_chunks`, `cveta2-minio`
- UI, Traefik, аналитика (ClickHouse, Vector, Grafana) и лишние воркеры
  не запускаются — порт сервера проброшен напрямую
- Создаёт пользователя-администратора
- Наполняет CVAT тестовым проектом `coco8-dev` (7 задач, 80 меток)

Чтобы указать конкретную версию CVAT:

```bash
./scripts/integration_up.sh --cvat-version v2.26.0
```

Чтобы использовать нестандартный порт (например, если 8080 занят):

```bash
./scripts/integration_up.sh --port 9080
```

В этом случае CVAT будет доступен на `http://localhost:9080`.

#### 2. Запуск интеграционных тестов

```bash
# Только интеграционные тесты (параллельно)
CVAT_INTEGRATION_HOST=http://localhost:8080 uv run pytest -m integration

# Все тесты (юнит + интеграционные, параллельно)
CVAT_INTEGRATION_HOST=http://localhost:8080 uv run pytest

# В один поток (для отладки)
CVAT_INTEGRATION_HOST=http://localhost:8080 uv run pytest -n0
```

Переменная окружения `CVAT_INTEGRATION_HOST` управляет активацией
интеграционных тестов. Если она не задана — запускаются только тесты
на JSON-фикстурах.

#### 3. Остановка

```bash
docker compose --project-directory vendor/cvat \
  -f vendor/cvat/docker-compose.yml \
  -f tests/integration/docker-compose.override.yml \
  --env-file tests/integration/.env \
  down -v
```

### Как это работает

Сессионная фикстура `coco8_fixtures` условно параметризована:

- **Без** `CVAT_INTEGRATION_HOST`: только параметр `"json"` (загрузка
  из `tests/fixtures/cvat/coco8-dev/`)
- **С** `CVAT_INTEGRATION_HOST`: оба параметра — `"json"` и `"live"`
  (live получает данные из реального CVAT через `SdkCvatApiAdapter`)

Тесты, зависящие от `coco8_fixtures` (test_mapping, test_extractors,
test_pipeline_integration, test_fetch_task), автоматически прогоняются
на обоих бэкендах без дублирования кода.

End-to-end тесты в `tests/integration/test_e2e.py` напрямую используют
реальный SDK-адаптер, CvatClient и CLI-команды.

## Корпоративный прокси / Кастомный Docker-реестр

Если Docker Hub недоступен из-за корпоративного прокси, настройте
зеркало реестра в Docker daemon (`/etc/docker/daemon.json`):

```json
{ "registry-mirrors": ["https://registry.corp.com"] }
```

Все образы (CVAT, PostgreSQL, Redis, OPA, MinIO и т.д.) будут
загружаться через указанное зеркало. Версии образов берутся из
`docker-compose.yml` того тега CVAT, который был выбран через
`--cvat-version`.

## Справка по переменным окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `CVAT_INTEGRATION_HOST` | _(не задана)_ | URL CVAT; включает интеграционные тесты |
| `CVAT_INTEGRATION_USER` | `admin` | Имя пользователя CVAT для интеграционных тестов |
| `CVAT_INTEGRATION_PASSWORD` | `admin` | Пароль CVAT для интеграционных тестов |

Порт задаётся через `--port` флаг скрипта `integration_up.sh`, а не
через переменную окружения. Он влияет только на маппинг хост-порта.

## Решение проблем

### Конфликт портов

CVAT API слушает на порту 8080 по умолчанию (проброс напрямую, без
Traefik), MinIO — 9000/9001. Если порт 8080 занят, используйте `--port`:

```bash
./scripts/integration_up.sh --port 9080
```

Для MinIO можно изменить маппинг портов в
`tests/integration/docker-compose.override.yml`.

### CVAT не запускается

Скрипт ждёт до 180 секунд. Если CVAT не стартует — проверьте логи:

```bash
docker compose --project-directory vendor/cvat \
  -f vendor/cvat/docker-compose.yml \
  -f tests/integration/docker-compose.override.yml \
  --env-file tests/integration/.env \
  logs cvat_server
```

### Сабмодуль не инициализирован

```
ERROR: CVAT submodule not initialized at vendor/cvat/
```

Решение: `git submodule update --init`

### Устаревшие тестовые данные

Если тесты падают после изменения фикстур, перезапустите скрипт:

```bash
./scripts/integration_up.sh
```

Он всегда сбрасывает CVAT в чистое состояние перед заполнением данными.

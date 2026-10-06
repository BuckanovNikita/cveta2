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
`kubectl` с контекстом `docker-desktop` и скилл `k8s-infra` (только для
интеграционных тестов).

Версии Python в проекте различаются намеренно: `requires-python = ">=3.10"` —
это floor **пакета**; `.python-version` пинит **разработку** на 3.12; mypy
анализирует как 3.11 (floor установленных зависимостей, см. ниже). Ставить
везде одно число не нужно и вредно.

Сабмодулей у репозитория нет: интеграционные тесты ходят на общие стенды
кластера и ничего не собирают локально (см. «Интеграционные тесты»).

## Разработка через Spec Kit

Изменения поведения, включая исправления ошибок, проходят через Spec Kit.
Правила проекта зафиксированы в
[конституции](.specify/memory/constitution.md); рабочие инструкции — в
[инженерных правилах](.specify/memory/engineering.md), доступных через
[AGENTS.md](AGENTS.md). Настроены Codex и Claude, интеграция по умолчанию —
Codex. Требование закреплено в инструкциях репозитория; отдельного CI-гейта нет.

### Инструменты и установка

Репозиторий использует официальный Spec Kit **1.0.13**. CLI запускается через
закреплённую версию `uvx`, независимо от глобально установленного `specify`:

```bash
uvx --from git+https://github.com/github/spec-kit.git@v1.0.13 specify version
uvx --from git+https://github.com/github/spec-kit.git@v1.0.13 specify integration status --json
```

После клонирования повторная инициализация не нужна: общие шаблоны, Bash-скрипты,
манифесты в `.specify/` и скиллы обеих интеграций хранятся в репозитории.
Запустите или перезапустите агента в корне проекта, чтобы он обнаружил скиллы.
Spec Kit не добавляется в зависимости приложения. Инструкция для первоначальной
настройки нового клона без этих файлов:

```bash
uvx --from git+https://github.com/github/spec-kit.git@v1.0.13 specify init --here --force --non-interactive --integration codex --script sh
uvx --from git+https://github.com/github/spec-kit.git@v1.0.13 specify integration install claude --script sh
```

`init --force` может перезаписать управляемые файлы: используйте его только при
первоначальной настройке после проверки дерева и конфликтующих путей.
Существующий `CLAUDE.md` должен оставаться симлинком на `AGENTS.md`.

### Последовательность изменения

Команды ниже вызываются **в чате агента**, по одной с проверкой результата;
это не команды терминала. Конституция уже заполнена: шаг `constitution`
нужен при изменении правил проекта, а не перед каждой задачей.

| Шаг | Codex | Claude | Результат |
|---|---|---|---|
| Требования | `$speckit-specify` | `/speckit-specify` | `spec.md`: цель, поведение, совместимость, критерии приёмки |
| Уточнение | `$speckit-clarify` | `/speckit-clarify` | Устранённые неоднозначности требований |
| План | `$speckit-plan` | `/speckit-plan` | `plan.md` и необходимые проектные артефакты |
| Качество требований | `$speckit-checklist` | `/speckit-checklist` | Чеклист полноты и согласованности требований |
| Задачи | `$speckit-tasks` | `/speckit-tasks` | `tasks.md` с зависимостями и проверками |
| Анализ | `$speckit-analyze` | `/speckit-analyze` | Проверка согласованности спецификации, плана и задач |
| Реализация | `$speckit-implement` | `/speckit-implement` | Код, документация и проверки по задачам |
| Сверка результата | `$speckit-converge` | `/speckit-converge` | Проверка полноты и задачи для оставшихся пробелов |

Пример первого сообщения для новой возможности в Codex:

```text
$speckit-specify <опишите требуемое изменение и критерии приёмки; сохраняйте существующие CLI, API и формат датасета, если изменение контракта не запрошено>
```

Спецификация, план и задачи пишутся на английском и находятся в
`specs/<номер>-<имя>/`. Исходный код и текущая документация используются как
контекст; описывать заново всё приложение не требуется. До реализации должны
быть готовы `spec.md`, `plan.md` и `tasks.md`, разрешены неоднозначности,
нарушения конституции и блокирующие замечания анализа, проверены чеклисты.
Готовность пункта чеклиста означает качество требований, а не завершение кода.

План проверяется по конституции до исследования и после проектирования.
Проверки выбираются по изменённому поведению и включаются в задачи, даже если
общий шаблон называет тесты необязательными. Для исправления ошибки сохраните
наблюдение сбоя, воспроизведение, когда оно доступно, и результат проверки
исходного сценария. Недоступное воспроизведение обозначайте явно.

Выполняйте `implement` и `converge` повторно, пока обязательных незавершённых
задач не останется. Сохраняйте датированные результаты проверок и ограничения
рядом с артефактами изменения. Остальные скиллы помогают с реализацией,
диагностикой и ревью; отдельные конкурирующие спецификации и планы не создаются.
Встроенный workflow `speckit` содержит только четыре шага и не заменяет полную
последовательность проекта. Публикация задач в issues и другие внешние действия
требуют отдельного поручения.

### Возобновление и сопровождение спецификаций

Завершённая `spec.md` остаётся актуальным контрактом. При изменении той же
возможности выберите её каталог, обновите спецификацию и пройдите остальные
шаги начиная с `clarify`. Перед перегенерацией плана и задач прочитайте текущие
артефакты; согласуйте их с новой спецификацией и сохраняйте свидетельства
прошлых проверок. Независимая возможность получает новый каталог через
`specify`. Завершённость задач подтверждается проверками.

Активная возможность выбирается через локальный `.specify/feature.json`
(игнорируется Git) или переменную окружения. В новом клоне указатель отсутствует.
При возобновлении явно выберите существующий каталог:

```bash
export SPECIFY_FEATURE_DIRECTORY=specs/001-feature-name
.specify/scripts/bash/check-prerequisites.sh --paths-only --json
```

Замените пример на реальный каталог. Перед записью артефактов проверьте
`FEATURE_DIR` в ответе; `--paths-only` не меняет указатель и не проверяет наличие
самих документов. Переменная имеет приоритет над локальным указателем:
обновляйте её при переключении возможностей или выполняйте
`unset SPECIFY_FEATURE_DIRECTORY` перед созданием новой.
Переключение Git-ветки само по себе не переключает возможность. Ветки создаются
вручную по правилам репозитория; расширение Git не установлено.

Правки документации и обслуживание без изменения поведения допускаются без
каталога возможности, с подходящими существующими проверками. Хуки, мутационные
и интеграционные гейты продолжают действовать; Spec Kit их не заменяет и не
разрешает автоматически коммит, пуш или релиз.

### Обновление Spec Kit

Обновляйте версию отдельным проверяемым изменением: изучите официальный релиз,
выберите точный тег, проверьте рабочее дерево и обновите обе интеграции через
`specify integration upgrade codex` и `specify integration upgrade claude`,
запуская CLI через `uvx --from git+https://github.com/github/spec-kit.git@<тег>`.
Сохраните Codex интеграцией по умолчанию. Если CLI обнаружит локально изменённые
управляемые файлы, сначала разберите различия; не обходите защиту через `--force`
без проверки. Затем проверьте diff, манифесты, статус интеграций, Bash-скрипты,
работу с тестовой возможностью в отдельной временной копии и документацию.
Обновите закреплённую версию и примеры установки в этой инструкции.

Официальные справочники:
[существующие проекты](https://github.github.io/spec-kit/guides/existing-projects.html),
[последовательность SDD](https://github.com/github/spec-kit/blob/v1.0.13/docs/quickstart.md),
[интеграции](https://github.com/github/spec-kit/blob/v1.0.13/docs/reference/integrations.md).

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
export CVAT_HOST="<url сервера CVAT>"
export CVAT_USERNAME="<пользователь>"
export CVAT_PASSWORD="<пароль>"
uv run python scripts/export_cvat_fixtures.py --project coco8-dev
```

Скрипт работает в личном рабочем пространстве этого пользователя (организацию
он не задаёт), поэтому проекты интеграционных прогонов на общем стенде ему не
видны.

По умолчанию вывод в `tests/fixtures/cvat/coco8-dev/`. Другой каталог: `--output-dir path`.

**Фейковые проекты** — для тестов можно собирать из базовых фикстур: произвольный набор задач, с повторами, случайными или заданными именами и статусами. Модуль `tests/fixtures/fake_cvat_project.py`: `FakeProjectConfig` (pydantic) и `build_fake_project(base_fixtures, config)`.

### Интеграционные тесты

Прогоняют тесты против живых CVAT, MinIO и ClearML — общих стендов локального
Kubernetes-кластера, которыми владеет скилл `k8s-infra`. На этой машине ничего
не поднимается: нет контейнеров, томов и портов, скрипты стенды не запускают и
не гасят. Прогон действует как проект `cveta2` реестра скилла (`projects.toml`)
под одним **тегом прогона**; контракт — `references/run-contract.md` скилла,
выжимка для агентов — блок «Shared infra» в
[инженерных правилах Spec Kit](.specify/memory/engineering.md#shared-infra).

```bash
# 0. Один раз: включить машину (кредов в файле нет, важен сам факт его наличия)
cp tests/integration/.env.example tests/integration/.env

# 1. Подготовить прогон: проверить учётку на стенде, выбить тег, засеять бакет и проект
./scripts/integration_up.sh

# 2. Запустить тесты (скрипт сам выставляет env-переменные и отключает xdist)
./scripts/integration_test.sh
./scripts/integration_test.sh -k upload        # только upload-тесты
./scripts/integration_test.sh -x --tb=long     # остановиться на первой ошибке

# 3. Убрать данные прогона со всех трёх стендов
./scripts/integration_stop.sh
```

**Креды.** Ни одного пароля в файлах нет: `scripts/integration_env.sh`
выполняет `cvat.py`, `minio.py` и `clearml.py --project cveta2 env` из скилла и
раскладывает ключи Secret'ов кластера по переменным, которые читают тесты
(`CVAT_INTEGRATION_*`, `MINIO_*`, `CLEARML_*`). Отсутствующий ключ — ошибка, а
не значение по умолчанию. Скилл ищется в `~/.agents/skills/k8s-infra`, затем в
`~/.claude/skills/k8s-infra`; другой checkout задаётся `K8S_INFRA_SKILL_DIR` —
единственное, что имеет смысл писать в `.env`.

**Тег.** `integration_env.sh` выводит один тег для up / test / stop / gate:
`INFRA_RUN_TAG`, если экспортирован (так подхватывают чужой или прерванный
прогон); на `main` — постоянный слот `cveta2-main`; иначе — тег из
`tests/integration/.run-tag`, который `integration_up.sh` записывает, выбив
свежий `infra.py newtag --project cveta2 --slug integration`, а
`integration_stop.sh` удаляет. Тег — единственный признак владения: проект
`<тег> coco8-dev` и облачное хранилище `<тег> minio` в организации из
Secret'а, бакет `<тег>` в MinIO, проекты `<тег> <что>` в ClearML (их тесты
создают и удаляют сами в конце сессии). Два прогона с разными тегами друг друга
не видят; сколько прогонов cveta2 допустимо одновременно, задаёт ключ
`[capacity].cveta2_integration_runs` в `projects.toml` скилла (CVAT видит все
прогоны с этой машины как одного клиента). Существующий `.run-tag` означает
активный прогон: `integration_up.sh` и гейт откажутся выбивать новый тег,
пока его не остановят или не подхватят через `INFRA_RUN_TAG`.

Перед засевом `integration_up.sh` проверяет учётку `cveta2` и её членство в
организации (`cvat_stand.py verify`; ничего не регистрирует — аккаунт создаёт
администратор стенда через `deploy_cvat.sh`) и удаляет всё с этим тегом,
поэтому повторный прогон всегда начинается с чистого проекта — именно так
upload-тесты не встречают собственных остатков (`Duplicate base task name`).

Посмотреть, что лежит на стендах, — от имени `cveta2`, без администратора:

```bash
source scripts/integration_env.sh
uv run python tests/integration/cvat_stand.py ls                       # объекты пользователя cveta2 в организации
python3 "$INTEGRATION_SKILL_DIR/scripts/cvat.py"    --project cveta2 ls --prefix "$INTEGRATION_RUN_TAG"
python3 "$INTEGRATION_SKILL_DIR/scripts/minio.py"   --project cveta2 ls --prefix "$INTEGRATION_RUN_TAG"
python3 "$INTEGRATION_SKILL_DIR/scripts/clearml.py" --project cveta2 ls --prefix "$INTEGRATION_RUN_TAG"
```

В браузере: интерфейс CVAT (`CVAT_INTEGRATION_HOST`) — под пользователем
`cveta2` с паролем из Secret'а, консоль MinIO (`MINIO_CONSOLE`) — с ключом
проекта; значения берите из окружения, не печатайте и не вставляйте в файлы.

`integration_stop.sh` удаляет объекты только своего тега: сначала CVAT
(`cvat_stand.py cleanup --tag`, селектор `"<тег> "` с пробелом, чтобы короткий
тег не задел длинный), потом бакет (`minio.py cleanup --prefix`), потом
проекты ClearML (`clearml.py cleanup --prefix`). `.run-tag` отпускается только
при полном успехе; при сбое скрипт печатает команду повтора для того же тега.
Сироты от погибших прогонов — дело скилла: `cleanup --stale --dry-run` их
перечисляет, а удаляет только уборщик кластера. Подробности и работа
параллельных агентов — в скилле `running-integration-tests`.

Без `CVAT_INTEGRATION_HOST` интеграционные тесты не собираются;
`integration_test.sh` выставляет её сам. Тесты ClearML не пропускаются:
`integration_test.sh` сначала требует, чтобы `clearml.py --project cveta2 whoami`
узнал учётку `cveta2`, и запускает pytest как `uv run --extra clearml` (SDK —
опциональная extra; обычный `uv sync` её убирает).

### Гейт на pre-push

`scripts/integration_gate.sh` (хук `integration-tests`) делает на пуше весь цикл
сам: проверяет стенд CVAT и учётку ClearML, убеждается, что в этом checkout нет
активного прогона, и только потом взводит teardown, готовит прогон, гоняет
`tests/integration`, а дальше смотрит на ветку.
Прогон с `main` (пуш `refs/heads/main` или `main` в рабочей копии) — это слот
`cveta2-main`, постоянное имя реестра: он **остаётся**, чтобы последний прогон
можно было открыть в интерфейсе CVAT; уборщик его не трогает, следующий прогон
с `main` его заменяет (в ClearML ничего не остаётся — тесты удаляют свои
проекты сами). Прогон с любой другой ветки убирает за собой.
`INTEGRATION_KEEP_DATA=1` оставляет прогон на любой ветке (это обычный тег:
уборщик снесёт его по истечении `[contract].stale_hours` реестра, а `.run-tag`
останется, и следующий гейт откажет, пока не выполнить `integration_stop.sh`);
`=0` убирает на любой ветке, на `main` — очищает слот до следующего прогона.
`--keep-stack` оставляет только упавший прогон.

Прогоняется только `tests/integration` — переменная `CVAT_INTEGRATION_HOST`
заодно добавляет параметр `live-cvat` в фикстуру `coco8_fixtures`, и юнит-тесты
пошли бы по живому CVAT ещё раз, последовательно. Такой прогон запускают руками:
`./scripts/integration_test.sh`.

Гейт включается сам по наличию `tests/integration/.env` — файл в `.gitignore`,
поэтому на свежем клоне и на любой другой машине интеграционных тестов на пуше
просто нет. Включить: `cp tests/integration/.env.example tests/integration/.env`.

Два следствия, о которых лучше знать заранее:

- **Пуш пересоздаёт данные своего тега.** `integration_up.sh` всегда начинает с
  удаления прошлого проекта тега в CVAT и его бакета — свежее состояние здесь
  требование корректности; на `main` это и есть замена слота.
- **Отсутствие `.env` — единственный тихий пропуск.** Если машина включена, а
  стенд не отвечает, Secret не читается или учётка ClearML не проходит, гейт
  валит пуш и предлагает диагностировать стенд скиллом `k8s-infra`; сами
  скрипты стенды не разворачивают.

Пропустить гейт на один пуш (`mutmut-full` при этом отработает):

```bash
SKIP=integration-tests git push
```

| Переменная | Откуда | Описание |
|---|---|---|
| `INFRA_RUN_TAG` | экспорт в shell | Явный тег прогона: подхватить чужой или прерванный либо выбитый `infra.py newtag --project cveta2` |
| `INFRA_HARNESS` | экспорт в shell | Кто запускает (`codex`, `ci`, `human`); без неё тег помечается `claude` |
| `INTEGRATION_RUN_TAG` | выводит `integration_env.sh` | Тег текущего прогона — читать, не задавать |
| `INTEGRATION_KEEP_DATA` | по ветке | `1` — оставить прогон после гейта, `0` — убрать |
| `K8S_INFRA_SKILL_DIR` | `.env` | Checkout скилла `k8s-infra`, если он не установлен в `~/.agents/skills` или `~/.claude/skills` |
| `CVAT_INTEGRATION_HOST`, `_USER`, `_PASSWORD`, `_ORG` | Secret `cvat/cvat-cveta2-access` | URL стенда (включает интеграционные тесты), учётка `cveta2` и организация всех объектов |
| `CVAT_INTEGRATION_PROJECT` | `<тег> coco8-dev` | Полное имя засеянного проекта |
| `MINIO_ENDPOINT`, `MINIO_ENDPOINT_FOR_CVAT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_REGION`, `MINIO_CONSOLE` | Secret `minio/minio-cveta2-access` | MinIO глазами хоста и глазами подов CVAT, ключ проекта, регион, консоль |
| `MINIO_BUCKET` | `<тег>` | Бакет прогона |
| `CLEARML_API_HOST`, `CLEARML_WEB_HOST`, `CLEARML_FILES_HOST`, `CLEARML_API_ACCESS_KEY`, `CLEARML_API_SECRET_KEY`, `CLEARML_QUEUE` | Secret `clearml/clearml-cveta2-access` | Учётка `cveta2` в ClearML, как её экспортирует скилл |

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
`ORG/PROJECT`, обработка удалённых кадров) — в [архитектурном контексте Spec Kit](.specify/memory/architecture.md).

## Документация

| Файл | Для кого | Язык |
|---|---|---|
| `README.md` | Пользователей — точка входа | Русский |
| `docs/cli.md` | Пользователей — команды CLI | Русский |
| `docs/configuration.md` | Пользователей — конфиг и окружение | Русский |
| `docs/images-and-cache.md` | Пользователей — S3, кэш, ClearML | Русский |
| `docs/python-api.md` | Пользователей — Python API | Русский |
| `CONTRIBUTING.md` | Разработчиков | Русский |
| [specs/001-project-documentation/contracts/dataset-format.md](specs/001-project-documentation/contracts/dataset-format.md) | Контракт выходных CSV для агентов и потребителей данных | Английский |
| [.specify/memory/architecture.md](.specify/memory/architecture.md) | Контекст для планирования: карта модулей и потоки данных | Английский |
| [.specify/memory/engineering.md](.specify/memory/engineering.md) | Подробные правила работы агентов | Английский |
| [.specify/memory/constitution.md](.specify/memory/constitution.md) | Принципы и управление процессом Spec Kit | Английский |
| [specs/001-project-documentation/](specs/001-project-documentation/) | Спецификация миграции, контракт датасета и датированные свидетельства | Английский |
| `AGENTS.md` (`CLAUDE.md` — симлинк на него) | Точка входа к источникам Spec Kit | Английский |

Правило: пользовательская и контрибьюторская документация (`README.md`,
`CONTRIBUTING.md`, `docs/`) — на русском; документация для разработчиков и
агентов (`AGENTS.md`, `.specify/memory/`, `specs/`) — на английском.
Архитектура и контракт датасета остаются актуальными источниками при последующих
изменениях; исторические обзоры в `evidence/` сохраняют дату и решения исходного
ревью, а не задают новую очередь исправлений.
`tests/test_docs.py` это проверяет.

Обновляйте `docs/` и затронутые контракты Spec Kit при изменении CLI или API —
`tests/test_docs.py` проверяет также `.specify/memory/` и `specs/` и падает,
если появилась недокументированная команда, флаг, переменная окружения или
поле конфига, если документированный Python-пример разошёлся с сигнатурой,
или если ссылка перестала резолвиться.

## Решение проблем

**Стенд не отвечает или Secret не читается** — `source scripts/integration_env.sh`
называет, какого стенда или ключа не хватает; `uv run python tests/integration/cvat_stand.py verify`
проверяет учётку `cveta2` и её членство в организации. Сами стенды описаны в
скилле `k8s-infra`; скрипты их не разворачивают

**`a run is active`** — в `tests/integration/.run-tag` записан тег
незавершённого прогона: `./scripts/integration_stop.sh` его уберёт, либо
`export INFRA_RUN_TAG=<тег>`, чтобы продолжить под ним

**`infra.py room` отвечает WAIT** — кластер занят; это не ошибка, подождите и
повторите

**Тесты падают после изменения фикстур** — перезапустите `./scripts/integration_up.sh`

**Пуш падает на `integration-tests`** — стенд не отвечает, Secret не читается
или в checkout активен другой прогон. Диагностируйте стенд скиллом `k8s-infra`
либо пропустите гейт на этот пуш: `SKIP=integration-tests git push`

**Пуш падает на `version-drift`** — `version` в `pyproject.toml` разошёлся с
ближайшим тегом. Верните значение, которое проставил релиз; если ветка старше
последнего релиза `main`, перебазируйте её на `main`.

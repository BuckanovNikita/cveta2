# Скрипты (scripts/)

Два инструмента разработки, оба запускаются из корня репозитория через
`uv run python`. Остальная обвязка живёт там, где её используют:

| Что | Где |
|---|---|
| Проверка сообщения коммита и дрейфа версии | `.pre-commit-config.yaml` (готовый хук `conventional-pre-commit` и встроенная команда `version-drift`) |
| Проверка владения эффектами (дополняет import-linter) | `tests/architecture_effects.py`, запускается из `tests/test_architecture.py` |
| Жизненный цикл интеграционного прогона (up / test / stop / gate / env) | `tests/integration/lifecycle.py`, см. скилл `running-integration-tests` |
| Клонирование CVAT-проекта в S3 cloud storage | `tests/integration/clone_project_to_s3.py` |

## benchmark_fetch.py

Замеряет реальный конвейер `fetch` с контролируемой задержкой удалённых вызовов и локальными файлами.

**Назначение:** воспроизвести сравнение производительности из [замеров фичи 001](../specs/001-fetch-speed-diagnostics/evidence/benchmark.md). Живые CVAT/S3 не нужны: удалённые вызовы — фикстуры внутри процесса с фиксированной искусственной задержкой, поэтому результаты сравнивают нагрузки, а не предсказывают пропускную способность сети.

```bash
uv run python -m scripts.benchmark_fetch --label working-tree --output after.json
```

---

## mutation.py

Запускает мутационное тестирование (mutmut) и превращает его результат в вердикт pass/fail.

**Назначение:** `mutmut run` всегда завершается с кодом 0 и не имеет порогового флага, поэтому гейт собирается отдельно: `mutmut export-cicd-stats` пишет `mutants/mutmut-cicd-stats.json`, `mutmut results` — список неубитых мутантов, а скрипт сверяет их с allowlist из `[tool.cveta2.mutation.equivalent]` в `pyproject.toml`.

**Зависимости:** mutmut (dev-группа). cveta2 не импортируется.

**Примеры:**

```bash
# Весь текущий охват из [tool.mutmut].only_mutate
uv run python scripts/mutation.py

# Один модуль или конкретные мутанты
uv run python scripts/mutation.py 'cveta2.domain.partition.*'

# Профиль pre-commit (подмножество охвата) и профиль pre-push (весь охват)
uv run python scripts/mutation.py --profile fast
uv run python scripts/mutation.py --profile full

# Ограничить параллелизм
uv run python scripts/mutation.py --max-children 4
```

`--profile` — единственный флаг, который передают сами хуки: `fast` на
pre-commit, `full` на pre-push. Профили заданы в
`[tool.cveta2.mutation.profiles]`; `full` — намеренно пустой список глобов,
потому что mutmut использует кэш вердиктов только когда позиционные имена
мутантов не заданы. Остальные аргументы (включая `--max-children`)
пробрасываются в mutmut как есть.

**Код возврата:** 0 — все мутанты убиты либо перечислены в allowlist; 1 — выжил мутант без обоснования **или** запись allowlist больше не соответствует живому мутанту (mutmut перенумеровывает мутантов при изменении функции).

**Вывод:** `mutants/mutmut-cicd-stats.json` (счётчики), `mutants/mutmut-results.txt` (имена и статусы). Каталог `mutants/` — рабочая копия mutmut, он в `.gitignore`.

Скрипт срезает CR-спиннер mutmut, когда stdout не терминал: иначе pre-commit сохранил бы десятки тысяч кадров перерисовки. Перед прогоном он сверяет «отпечаток» охвата (`only_mutate`, `do_not_mutate_patterns` и т. п.) и пересоздаёт `mutants/`, если охват изменился: собственный отпечаток mutmut эти поля не учитывает.

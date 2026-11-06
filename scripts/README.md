# Скрипты (scripts/)

Вспомогательные скрипты для разработки и тестов. Проверки архитектуры, сообщения коммита и версии живут в `tests/` и `.pre-commit-config.yaml`, помощник клонирования проекта в S3 — в `tests/integration/clone_project_to_s3.py`. Запускать из корня
репозитория: Python-скрипты через `uv run python scripts/<script>.py ...`,
shell-скрипты — напрямую (`./scripts/<script>.sh`).

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

## Остальные скрипты

Отдельных разделов у них нет — они описаны там, где используются:

| Скрипт | Где описан |
|---|---|
| `integration_env.sh`, `integration_up.sh`, `integration_test.sh`, `integration_stop.sh`, `integration_gate.sh` | Скилл `running-integration-tests` (`.claude/skills/running-integration-tests/SKILL.md`) |

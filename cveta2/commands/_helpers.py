"""Shared helpers for CLI commands."""

from __future__ import annotations

import sys
from pathlib import Path  # noqa: TC003

import pandas as pd
import questionary
from loguru import logger

from cveta2.client import CvatClient  # noqa: TC001
from cveta2.config import CvatConfig, get_config_path, require_interactive
from cveta2.models import ProjectAnnotations  # noqa: TC001
from cveta2.projects_cache import load_projects_cache, save_projects_cache

_RESCAN_VALUE = "__rescan__"


def resolve_project_from_args(
    project_arg: str | None,
    client: CvatClient,
) -> tuple[int, str] | None:
    """Resolve project ID and name from CLI project argument.

    When *project_arg* is non-empty, resolves via cache and returns
    ``(project_id, project_name)``. When *project_name* is a digit string,
    looks up human-readable name from cache. Returns ``None`` when
    *project_arg* is None or empty (caller should run interactive TUI).

    Raises
    ------
    Cveta2Error
        When project is not found (e.g. ProjectNotFoundError).

    """
    if not project_arg or not project_arg.strip():
        return None
    cached = load_projects_cache()
    project_id = client.resolve_project_id(project_arg.strip(), cached=cached)
    project_name = project_arg.strip()
    if project_name.isdigit():
        for p in cached:
            if p.id == project_id:
                project_name = p.name
                break
    return (project_id, project_name)


def select_project_tui(client: CvatClient) -> tuple[int, str]:
    """Interactive project selection via TUI list with rescan option.

    Returns ``(project_id, project_name)``.
    """
    require_interactive("Pass --project / -p to specify the project ID or name.")
    projects = load_projects_cache()
    while True:
        if not projects:
            logger.info("Кэш проектов пуст. Загружаю список с CVAT...")
            projects = client.list_projects()
            save_projects_cache(projects)
            if not projects:
                sys.exit("Нет доступных проектов.")
        choices: list[questionary.Choice] = [
            questionary.Choice(title=f"{p.name} (id={p.id})", value=p.id)
            for p in projects
        ]
        choices.append(
            questionary.Choice(
                title="↻ Обновить список проектов с CVAT",
                value=_RESCAN_VALUE,
            ),
        )
        answer = questionary.select(
            "Выберите проект:",
            choices=choices,
            use_shortcuts=False,
            use_indicator=True,
            use_search_filter=True,
            use_jk_keys=False,
        ).ask()
        if answer is None:
            sys.exit("Выбор отменён.")
        if answer == _RESCAN_VALUE:
            projects = client.list_projects()
            save_projects_cache(projects)
            logger.info(f"Загружено проектов: {len(projects)}")
            continue
        project_id = int(answer)
        project_name = str(project_id)
        for p in projects:
            if p.id == project_id:
                project_name = p.name
                break
        return (project_id, project_name)


def load_config(config_path: Path | None = None) -> CvatConfig:
    """Load config from file and env. Path from CVETA2_CONFIG or argument."""
    return CvatConfig.load(config_path=config_path)


def read_dataset_csv(
    path: Path,
    required_columns: set[str],
    *,
    require_time_column: bool = False,
) -> pd.DataFrame:
    """Read a dataset CSV and validate required columns.

    Exits with a message if the file is missing or columns are invalid.
    When *require_time_column* is True, ``task_updated_date`` must also be present.
    """
    if not path.is_file():
        sys.exit(f"Ошибка: файл не найден: {path}")
    df = pd.read_csv(path, encoding="utf-8")
    missing = required_columns - set(df.columns)
    if missing:
        sys.exit(
            f"Ошибка: в {path} отсутствуют обязательные столбцы: "
            f"{', '.join(sorted(missing))}"
        )
    if require_time_column and "task_updated_date" not in df.columns:
        sys.exit(
            f"Ошибка: --by-time требует столбец 'task_updated_date' "
            f"в {path}, но он отсутствует."
        )
    logger.info(f"Загружен {path}: {len(df)} строк")
    return df


def require_host(cfg: CvatConfig) -> None:
    """Abort with a friendly message when host is not configured."""
    if cfg.host:
        return
    config_path = get_config_path()
    sys.exit(
        "Ошибка: хост CVAT не настроен.\n"
        "Запустите setup для сохранения настроек:\n  cveta2 setup\n"
        "Или задайте переменные окружения: CVAT_HOST и "
        "(CVAT_TOKEN или CVAT_USERNAME/CVAT_PASSWORD).\n"
        f"Файл конфигурации: {config_path}"
    )


def write_dataset_and_deleted(
    result: ProjectAnnotations,
    output_dir: Path,
) -> None:
    """Write dataset.csv and deleted.txt from annotation result into *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = result.to_csv_rows()
    df = pd.DataFrame(rows)
    write_df_csv(df, output_dir / "dataset.csv", "Dataset CSV")
    deleted_names = [img.image_name for img in result.deleted_images]
    write_deleted_txt(deleted_names, output_dir / "deleted.txt")


def write_df_csv(df: pd.DataFrame, path: Path, label: str) -> None:
    """Write a DataFrame to CSV and log the result."""
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info(f"{label} saved to {path} ({len(df)} rows)")


def write_deleted_txt(deleted_names: list[str], path: Path) -> None:
    """Write deleted image names to a text file, one per line."""
    content = "\n".join(deleted_names)
    if deleted_names:
        content += "\n"
    path.write_text(content, encoding="utf-8")
    logger.info(f"Deleted images list saved to {path} ({len(deleted_names)} names)")

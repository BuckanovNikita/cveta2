"""Shared helpers for CLI commands."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import questionary
from loguru import logger

from cveta2.config import (
    CvatConfig,
    get_config_path,
    load_sync_roots_config,
    require_interactive,
)
from cveta2.exceptions import Cveta2Error
from cveta2.projects_cache import load_projects_cache, save_projects_cache
from cveta2.s3_utils import parse_sync_root
from cveta2.services.output import read_dataset_csv as services_read_dataset_csv

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd

    from cveta2.client import CvatClient
    from cveta2.image_downloader import CloudStorageInfo

_RESCAN_VALUE = "__rescan__"


def resolve_project_from_args(
    project_arg: str | None,
    client: CvatClient,
) -> tuple[int, str] | None:
    """Resolve project ID and name from CLI project argument.

    When *project_arg* is non-empty, resolves via cache and returns
    ``(project_id, project_name)``. When *project_arg* is a digit string,
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


def resolve_project_or_exit(
    project_arg: str | None,
    client: CvatClient,
) -> tuple[int, str]:
    """Resolve project ID and name, falling back to interactive TUI.

    Calls :func:`resolve_project_from_args` and exits on error.
    When *project_arg* is empty, falls back to :func:`select_project_tui`.
    """
    try:
        resolved = resolve_project_from_args(project_arg, client)
    except Cveta2Error as e:
        sys.exit(str(e))

    if resolved is not None:
        return resolved
    return select_project_tui(client)


def resolve_project_and_cloud_storage(
    client: CvatClient,
    project_spec: str | None,
    *,
    sync_root: str | None = None,
) -> tuple[int, str, CloudStorageInfo | None]:
    """Resolve project ID, name, and project cloud storage from a spec.

    When *project_spec* is None or empty, uses interactive TUI to get
    (project_id, project_name). Otherwise uses :func:`resolve_project_from_args`.
    Then calls :meth:`CvatClient.detect_project_cloud_storage` and returns
    (project_id, project_name, cs_info). cs_info may be None if the project
    has no source_storage.

    The returned cloud storage bucket/prefix can be overridden by
    *sync_root* (a ``s3://bucket/prefix`` URL or a bare prefix) or, when
    it is None, by the ``sync_roots`` config section for this project.

    Raises
    ------
    Cveta2Error
        When project_spec is set but project is not found, or when the
        sync root is invalid.

    """
    if project_spec and project_spec.strip():
        resolved = resolve_project_from_args(project_spec.strip(), client)
        if resolved is None:
            project_id, project_name = select_project_tui(client)
        else:
            project_id, project_name = resolved
    else:
        project_id, project_name = select_project_tui(client)
    cs_info = client.detect_project_cloud_storage(project_id)
    cs_info = _apply_sync_root_override(project_name, cs_info, sync_root)
    return (project_id, project_name, cs_info)


def _apply_sync_root_override(
    project_name: str,
    cs_info: CloudStorageInfo | None,
    explicit_root: str | None,
) -> CloudStorageInfo | None:
    """Override cs_info bucket/prefix from an explicit root or sync_roots config."""
    root = explicit_root or load_sync_roots_config().get_root(project_name)
    if not root:
        return cs_info
    if cs_info is None:
        logger.warning(
            f"Проект {project_name!r}: задан корень синхронизации {root!r}, "
            f"но у проекта нет cloud storage — переопределение не применено."
        )
        return None
    try:
        bucket, prefix = parse_sync_root(root)
    except ValueError as e:
        raise Cveta2Error(str(e)) from e
    update: dict[str, str] = {"prefix": prefix}
    if bucket is not None:
        update["bucket"] = bucket
    overridden = cs_info.model_copy(update=update)
    logger.info(
        f"Проект {project_name!r}: корень синхронизации переопределён на "
        f"s3://{overridden.bucket}/{overridden.prefix}"
    )
    return overridden


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
    try:
        return services_read_dataset_csv(
            path,
            required_columns,
            require_time_column=require_time_column,
        )
    except Cveta2Error as e:
        sys.exit(str(e))


def require_host(cfg: CvatConfig) -> None:
    """Abort with a friendly message when host is not configured."""
    if cfg.host:
        return
    config_path = get_config_path()
    sys.exit(
        "Ошибка: хост CVAT не настроен.\n"
        "Запустите setup для сохранения настроек:\n  cveta2 setup\n"
        "Или задайте переменные окружения: CVAT_HOST и "
        "(CVAT_USERNAME/CVAT_PASSWORD).\n"
        f"Файл конфигурации: {config_path}"
    )

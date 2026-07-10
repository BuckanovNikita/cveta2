"""Shared helpers for CLI commands."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from cveta2.commands.interactive import select_project
from cveta2.config import (
    CvatConfig,
    get_config_path,
)
from cveta2.projects_cache import load_projects_cache
from cveta2.services.resolve import apply_sync_root_override

if TYPE_CHECKING:
    from cveta2.client import CvatClient
    from cveta2.image_downloader import CloudStorageInfo


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


def resolve_project(
    project_arg: str | None,
    client: CvatClient,
) -> tuple[int, str]:
    """Resolve project ID and name, falling back to interactive TUI.

    Calls :func:`resolve_project_from_args`; a :class:`Cveta2Error` (e.g.
    project not found) propagates to the CLI dispatch boundary.  When
    *project_arg* is empty, falls back to :func:`select_project`.
    """
    resolved = resolve_project_from_args(project_arg, client)
    if resolved is not None:
        return resolved
    return select_project(client)


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
            project_id, project_name = select_project(client)
        else:
            project_id, project_name = resolved
    else:
        project_id, project_name = select_project(client)
    cs_info = client.detect_project_cloud_storage(project_id)
    cs_info = apply_sync_root_override(project_name, cs_info, sync_root)
    return (project_id, project_name, cs_info)


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

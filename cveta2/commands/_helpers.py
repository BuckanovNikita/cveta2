"""Shared helpers for CLI commands."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands.interactive import select_project
from cveta2.config import (
    CvatConfig,
    get_config_path,
)
from cveta2.exceptions import MissingHostError
from cveta2.projects_cache import PERSONAL_WORKSPACE_SLUG, load_projects_cache
from cveta2.services.resolve import (
    apply_project_org,
    project_cloud_storage,
    resolve_bare_project_spec,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

    from cveta2.client import CvatClient
    from cveta2.image_downloader import CloudStorageInfo


# Module level so mutation testing cannot generate unkillable "reword the
# error" mutants inside :func:`require_host`.
_MISSING_HOST_MESSAGE = (
    "Ошибка: хост CVAT не настроен.\n"
    "Запустите setup для сохранения настроек:\n  cveta2 setup\n"
    "Или задайте переменные окружения: CVAT_HOST и "
    "(CVAT_USERNAME/CVAT_PASSWORD).\n"
    "Файл конфигурации: {config_path}"
)


def echo_cli_command(subcommand: str, arg_values: Mapping[str, object]) -> None:
    """Print the fully-resolved CLI command to stdout for re-running.

    *arg_values* maps flags to resolved values in CLI order: ``None``/
    ``False`` entries are dropped, ``True`` renders a bare flag, lists
    render as ``--flag v1 v2``.  The command goes to stdout (not the
    loguru stderr sink) so it can be copy-pasted or piped.
    """
    parts = ["cveta2", subcommand]
    for flag, value in arg_values.items():
        if value is None or value is False:
            continue
        if value is True:
            parts.append(flag)
        elif isinstance(value, (list, tuple)):
            if value:
                parts.append(flag)
                parts.extend(shlex.quote(str(v)) for v in value)
        else:
            parts.extend((flag, shlex.quote(str(value))))
    logger.info("Команда для повторного запуска:")
    sys.stdout.write(" ".join(parts) + "\n")


def echo_if_prompted(
    subcommand: str,
    arg_values: Mapping[str, object],
    *,
    prompted: bool,
) -> None:
    """Echo the reproducible command when any input came from a prompt.

    Every command computes its own ``prompted`` predicate (were any of
    its inputs resolved interactively?) and routes the echo through here,
    so the "echo only after prompting" rule lives in one place.
    """
    if prompted:
        echo_cli_command(subcommand, arg_values)


def config_path_from_args(args: argparse.Namespace) -> Path:
    """Resolve the ``--config`` argument into a concrete config path."""
    config_arg = getattr(args, "config", None)
    return Path(config_arg) if config_arg else get_config_path()


def resolve_project_from_args(
    client: CvatClient,
    project_arg: str | None,
) -> tuple[int, str] | None:
    """Resolve project ID and name from CLI project argument.

    When *project_arg* is non-empty, returns ``(project_id, project_name)``
    with the name as CVAT spells it. An ``ORG/PROJECT`` spec switches the
    client's session organization first (``/PROJECT`` selects the
    personal workspace). The local projects cache of that organization is
    consulted before CVAT (see :func:`resolve_bare_project_spec`). Returns
    ``None`` when *project_arg* is None or empty (caller should run
    interactive TUI).

    Raises
    ------
    Cveta2Error
        When project is not found (e.g. ProjectNotFoundError).

    """
    if not project_arg or not project_arg.strip():
        return None
    spec = apply_project_org(client, project_arg.strip())
    cached = load_projects_cache(org=client.organization or PERSONAL_WORKSPACE_SLUG)
    return resolve_bare_project_spec(client, spec, cached=cached)


def resolve_project(
    client: CvatClient,
    project_arg: str | None,
) -> tuple[int, str]:
    """Resolve project ID and name, falling back to interactive TUI.

    Calls :func:`resolve_project_from_args`; a :class:`Cveta2Error` (e.g.
    project not found) propagates to the CLI dispatch boundary.  When
    *project_arg* is empty, falls back to :func:`select_project`.
    """
    resolved = resolve_project_from_args(client, project_arg)
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
    project_id, project_name = resolve_project(client, project_spec)
    cs_info = project_cloud_storage(client, project_id, project_name, sync_root)
    return (project_id, project_name, cs_info)


def project_cli_spec(client: CvatClient, project_name: str) -> str:
    """CLI value for ``-p``: prefixed with the org when it differs from config.

    Keeps echoed commands re-runnable when a project was picked from a
    non-default organization (``ORG/PROJECT``, or ``/PROJECT`` for the
    personal workspace).
    """
    current = client.organization or ""
    if current == (client.default_organization or ""):
        return project_name
    return f"{current}/{project_name}"


def require_host(cfg: CvatConfig) -> None:
    """Raise a friendly error when host is not configured."""
    if cfg.host:
        return
    raise MissingHostError(_MISSING_HOST_MESSAGE.format(config_path=get_config_path()))

"""Project name and cloud-storage resolution shared by CLI and public API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from cveta2.config import SyncRootsConfig
from cveta2.exceptions import CvatApiError, Cveta2Error
from cveta2.s3_utils import parse_sync_root

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from cveta2.client import CvatClient
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import ProjectInfo


def split_project_spec(project: int | str) -> tuple[str | None, int | str]:
    """Split an ``ORG/PROJECT`` spec into ``(org, project)``.

    Without a slash the org is ``None`` (keep the session default).  An
    empty org part (``/project``) means the personal workspace and is
    returned as ``""``.  Only the first slash separates the org.
    """
    if isinstance(project, int):
        return None, project
    spec = str(project).strip()
    if "/" not in spec:
        return None, spec
    org, _, name = spec.partition("/")
    name = name.strip()
    if not name:
        raise Cveta2Error(
            f"Некорректная спецификация проекта {spec!r}: "
            f"ожидается ORG/PROJECT или /PROJECT."
        )
    return org.strip(), name


def apply_project_org(client: CvatClient, project: int | str) -> int | str:
    """Switch the client org from an ``ORG/PROJECT`` spec; return the bare spec.

    ``ORG/PROJECT`` switches the session to ``ORG``; ``/PROJECT`` switches
    to the personal workspace; a bare spec keeps the session default
    (the configured organization).
    """
    org, spec = split_project_spec(project)
    if org is not None:
        client.set_organization(org or None)
    return spec


def _project_display_name(
    client: CvatClient,
    project_id: int,
    cached: list[ProjectInfo] | None = None,
) -> str:
    """Return the project's name, falling back to the id when unreadable.

    A matching entry in *cached* (the local projects cache) answers without
    a request.  Otherwise an id nobody owns must still produce a usable
    name: it ends up in log lines, in the task-cache directory and as the
    ignore-list key, and an empty one would be shown to the user verbatim.
    Reading the single project costs one request, where listing the whole
    organization to find its name costs one per page.
    """
    for p in cached or ():
        if p.id == project_id:
            return p.name
    try:
        return client.get_project(project_id).name or str(project_id)
    except CvatApiError as e:
        logger.info(
            f"Не удалось прочитать проект {project_id} ({e}) — "
            f"используем id как имя проекта"
        )
        return str(project_id)


def resolve_project_spec(
    client: CvatClient,
    project: int | str,
    *,
    cached: list[ProjectInfo] | None = None,
) -> tuple[int, str]:
    """Resolve a project spec to ``(project_id, project_name)``.

    Accepts an id, a name, or an ``ORG/PROJECT`` string (the org part
    switches the client's session organization; see
    :func:`apply_project_org`).  Never prompts — unlike the interactive
    :func:`cveta2.commands._helpers.resolve_project`.
    """
    spec = apply_project_org(client, project)
    return resolve_bare_project_spec(client, spec, cached=cached)


def resolve_bare_project_spec(
    client: CvatClient,
    spec: int | str,
    *,
    cached: list[ProjectInfo] | None = None,
) -> tuple[int, str]:
    """Resolve an id or a name (no ``ORG/`` prefix) to ``(project_id, project_name)``.

    The name is always CVAT's own spelling — from *cached* (the local
    projects cache, consulted first) or from CVAT — never the caller's:
    the name lookup is case-insensitive, and the returned name keys the
    ignore list, the image-cache directory and the ClearML dataset.
    """
    name = str(spec).strip()
    if isinstance(spec, int) or name.isdigit():
        project_id = client.resolve_project_id(spec)
        return project_id, _project_display_name(client, project_id, cached)
    project = client.find_project_by_name(name, cached=cached)
    return project.id, project.name


def infer_project_from_tasks(
    client: CvatClient,
    tasks: Sequence[int | str],
) -> int | None:
    """Return the project id of the first numeric task spec, or ``None``.

    Task names cannot be resolved without a project, so only numeric ids
    participate.  Raises :class:`Cveta2Error` when the task exists but
    belongs to no project.
    """
    for spec in tasks:
        text = str(spec).strip()
        if not (isinstance(spec, int) or text.isdigit()):
            continue
        task = client.get_task(int(text))
        if task.project_id is None:
            raise Cveta2Error(
                f"Задача {task.id} не принадлежит ни одному проекту — "
                f"укажите проект явно."
            )
        logger.info(
            f"Проект определён по задаче {task.name!r} (id={task.id}): "
            f"project_id={task.project_id}"
        )
        return task.project_id
    return None


def project_cloud_storage(
    client: CvatClient,
    project_id: int,
    project_name: str,
    root: str | None = None,
    *,
    config_path: Path | None = None,
) -> CloudStorageInfo | None:
    """Detect the project's cloud storage and apply any sync-root override.

    The pair is always composed together — detecting storage without
    honouring ``sync_roots`` would download from the wrong bucket — so it
    lives here rather than being spelled out at each call site.
    """
    return apply_sync_root_override(
        project_name,
        client.detect_project_cloud_storage(project_id),
        root,
        config_path=config_path,
    )


def apply_sync_root_override(
    project_name: str,
    cs_info: CloudStorageInfo | None,
    explicit_root: str | None = None,
    *,
    config_path: Path | None = None,
) -> CloudStorageInfo | None:
    """Override cs_info bucket/prefix from an explicit root or sync_roots config."""
    root = explicit_root or SyncRootsConfig.load(config_path).get_root(project_name)
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

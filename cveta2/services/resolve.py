"""Project name and cloud-storage resolution shared by CLI and public API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from cveta2.config import load_sync_roots_config
from cveta2.exceptions import Cveta2Error
from cveta2.s3_utils import parse_sync_root

if TYPE_CHECKING:
    from cveta2.client import CvatClient
    from cveta2.image_downloader import CloudStorageInfo


def resolve_project(client: CvatClient, project: int | str) -> tuple[int, str]:
    """Resolve a project spec (id or name) to ``(project_id, project_name)``."""
    project_id = client.resolve_project_id(project)
    name = str(project).strip()
    if isinstance(project, int) or name.isdigit():
        name = next(
            (p.name for p in client.list_projects() if p.id == project_id),
            str(project_id),
        )
    return project_id, name


def apply_sync_root_override(
    project_name: str,
    cs_info: CloudStorageInfo | None,
    explicit_root: str | None = None,
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

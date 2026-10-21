"""Implementation of the ``cveta2 s3-sync`` command."""

from typing import TYPE_CHECKING, NamedTuple

from loguru import logger

from cveta2.composition.configuration import (
    CacheConfig,
    ImageCacheConfig,
    images_cache_dir_from,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.interfaces.commands._bootstrap import open_client
from cveta2.interfaces.commands._helpers import (
    resolve_project_and_cloud_storage,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from cveta2.composition.client import CvatClient
    from cveta2.domain.storage import CloudStorageInfo


from cveta2.interfaces.commands._parsers import add_project_arg


def configure_s3_sync(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``s3-sync`` command arguments."""
    add_project_arg(
        parser,
        help_text=(
            "Sync only this project (name from image_cache config). "
            "If omitted, syncs every configured project."
        ),
    )
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help=(
            "One-run override of the S3 sync root "
            "(s3://bucket/prefix or a bare prefix). "
            "Takes priority over the sync_roots config section. "
            "Requires --project."
        ),
    )


class SyncTarget(NamedTuple):
    """Where one project's images live locally, and how to lay them out."""

    cache_dir: "Path"
    ignored_prefix: str | None


def _resolve_sync_dirs(project_filter: str | None) -> "dict[str, SyncTarget]":
    """Map project name → local image dir from ``image_cache`` + ``cache``.

    Both sections are loaded once here, so the per-project resolution and
    ``ignored_prefix`` lookup do not re-parse the YAML once per project.
    """
    ic_cfg = ImageCacheConfig.load()
    cache_cfg = CacheConfig.load()

    names = set(ic_cfg.projects) | set(cache_cfg.projects)
    if project_filter:
        names = {project_filter}
    resolved: dict[str, SyncTarget] = {}
    for name in sorted(names):
        project_cache = cache_cfg.for_project(name)
        cache_dir = images_cache_dir_from(ic_cfg, project_cache, name)
        if cache_dir is None:
            continue
        resolved[name] = SyncTarget(cache_dir, project_cache.ignored_prefix)
    return resolved


def run_s3_sync(args: "argparse.Namespace") -> None:
    """Run the ``s3-sync`` command."""
    if args.root and not args.project:
        raise Cveta2Error(
            "Ошибка: --root требует явного указания проекта через --project."
        )

    project_filter = args.project.strip() if args.project else None
    if project_filter:
        with open_client() as client:
            project_id, project_name, cs_info = resolve_project_and_cloud_storage(
                client, project_filter, sync_root=args.root
            )
            targets = _resolve_sync_dirs(project_name)
            if project_name not in targets:
                raise Cveta2Error(
                    f"Ошибка: для проекта {project_name!r} не настроен путь "
                    f"кэширования изображений.\n"
                    f"Добавьте image_cache.{project_name} или cache.images_root "
                    f"в конфигурацию (cveta2 setup-cache)."
                )
            _sync_project(
                client, project_id, project_name, cs_info, targets[project_name]
            )
        return

    projects_to_sync = _resolve_sync_dirs(None)
    if not projects_to_sync:
        raise Cveta2Error(
            "Ошибка: нет проектов для синхронизации — не настроены ни "
            "image_cache, ни cache.projects.\n"
            "Добавьте секцию image_cache в конфигурацию или запустите: "
            "cveta2 setup-cache"
        )

    with open_client() as client:
        skipped: list[str] = []
        for project_name, target in projects_to_sync.items():
            logger.info(f"--- Синхронизация проекта: {project_name} ---")
            try:
                project_id, _name, cs_info = resolve_project_and_cloud_storage(
                    client, project_name, sync_root=args.root
                )
            except Cveta2Error as e:
                logger.error(f"Проект {project_name!r}: не удалось определить ID — {e}")
                skipped.append(project_name)
                continue

            if not _sync_project(client, project_id, project_name, cs_info, target):
                skipped.append(project_name)
        if skipped:
            logger.warning(f"Синхронизация неполная: пропущены проекты {skipped}")


def _sync_project(
    client: "CvatClient",
    project_id: int,
    project_name: str,
    cs_info: "CloudStorageInfo | None",
    target: "SyncTarget",
) -> bool:
    """Sync a resolved project; return False when it has no cloud storage."""
    if cs_info is None:
        logger.warning(
            f"Проект {project_name!r}: cloud storage не найден — пропускаем."
        )
        return False
    stats = client.sync_project_images(
        project_id,
        target.cache_dir,
        project_cloud_storage=cs_info,
        ignored_prefix=target.ignored_prefix,
    )
    logger.info(f"Проект {project_name!r}: {stats.summary()}")
    return True

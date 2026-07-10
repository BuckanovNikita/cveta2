"""Implementation of the ``cveta2 s3-sync`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import (
    resolve_project_and_cloud_storage,
)
from cveta2.config import (
    cache_dir_for_project,
    load_cache_config,
    load_image_cache_config,
)
from cveta2.exceptions import Cveta2Error

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def _resolve_sync_dirs(project_filter: str | None) -> dict[str, Path]:
    """Map project name → local image dir from ``image_cache`` + ``cache``.

    Per-project ``image_cache`` entries win; projects known only to the
    ``cache`` section fall back to ``images_root/<sanitized_name>``.
    """
    ic_cfg = load_image_cache_config()
    cache_cfg = load_cache_config()

    names = set(ic_cfg.projects) | set(cache_cfg.projects)
    if project_filter:
        names = {project_filter}
    resolved: dict[str, Path] = {}
    for name in sorted(names):
        cache_dir = ic_cfg.get_cache_dir(name)
        if cache_dir is None:
            images_root = cache_cfg.for_project(name).images_root
            if images_root is None:
                continue
            cache_dir = cache_dir_for_project(images_root, name)
        resolved[name] = cache_dir
    return resolved


def run_s3_sync(args: argparse.Namespace) -> None:
    """Run the ``s3-sync`` command."""
    if args.root and not args.project:
        raise Cveta2Error(
            "Ошибка: --root требует явного указания проекта через --project."
        )

    project_filter = args.project.strip() if args.project else None
    projects_to_sync = _resolve_sync_dirs(project_filter)
    if not projects_to_sync:
        if project_filter:
            raise Cveta2Error(
                f"Ошибка: для проекта {project_filter!r} не настроен путь "
                f"кэширования изображений.\n"
                f"Добавьте image_cache.{project_filter} или cache.images_root "
                f"в конфигурацию (cveta2 setup-cache)."
            )
        raise Cveta2Error(
            "Ошибка: image_cache не настроен — нет проектов для синхронизации.\n"
            "Добавьте секцию image_cache в конфигурацию или запустите: cveta2 setup"
        )

    with open_client() as client:
        for project_name, cache_dir in projects_to_sync.items():
            logger.info(f"--- Синхронизация проекта: {project_name} ---")
            try:
                project_id, _name, cs_info = resolve_project_and_cloud_storage(
                    client, project_name, sync_root=args.root
                )
            except Cveta2Error as e:
                logger.error(f"Проект {project_name!r}: не удалось определить ID — {e}")
                continue

            if cs_info is None:
                logger.warning(
                    f"Проект {project_name!r}: cloud storage не найден — пропускаем."
                )
                continue

            ignored_prefix = (
                load_cache_config().for_project(project_name).ignored_prefix
            )
            stats = client.sync_project_images(
                project_id,
                cache_dir,
                project_cloud_storage=cs_info,
                ignored_prefix=ignored_prefix,
            )
            logger.info(
                f"Проект {project_name!r}: {stats.downloaded} загружено, "
                f"{stats.cached} из кэша, {stats.failed} ошибок "
                f"(всего {stats.total})"
            )

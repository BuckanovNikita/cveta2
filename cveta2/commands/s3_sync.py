"""Implementation of the ``cveta2 s3-sync`` command."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.client import CvatClient
from cveta2.commands._helpers import (
    require_host,
    resolve_project_and_cloud_storage,
)
from cveta2.config import CvatConfig, load_image_cache_config
from cveta2.exceptions import Cveta2Error

if TYPE_CHECKING:
    import argparse


def run_s3_sync(args: argparse.Namespace) -> None:
    """Run the ``s3-sync`` command."""
    cfg = CvatConfig.load()
    require_host(cfg)

    ic_cfg = load_image_cache_config()
    if not ic_cfg.projects:
        sys.exit(
            "Ошибка: image_cache не настроен — нет проектов для синхронизации.\n"
            "Добавьте секцию image_cache в конфигурацию или запустите: cveta2 setup"
        )

    # Filter to a single project if --project was given
    if args.project:
        project_name = args.project.strip()
        cache_dir = ic_cfg.get_cache_dir(project_name)
        if cache_dir is None:
            sys.exit(
                f"Ошибка: проект {project_name!r} не найден в image_cache.\n"
                f"Настроенные проекты: "
                f"{', '.join(ic_cfg.projects) or '(нет)'}"
            )
        projects_to_sync = {project_name: cache_dir}
    else:
        projects_to_sync = dict(ic_cfg.projects)

    with CvatClient(cfg) as client:
        for project_name, cache_dir in projects_to_sync.items():
            logger.info(f"--- Синхронизация проекта: {project_name} ---")
            try:
                project_id, _name, cs_info = resolve_project_and_cloud_storage(
                    client, project_name
                )
            except Cveta2Error as e:
                logger.error(f"Проект {project_name!r}: не удалось определить ID — {e}")
                continue

            if cs_info is None:
                logger.warning(
                    f"Проект {project_name!r}: cloud storage не найден — пропускаем."
                )
                continue

            stats = client.sync_project_images(
                project_id, cache_dir, project_cloud_storage=cs_info
            )
            logger.info(
                f"Проект {project_name!r}: {stats.downloaded} загружено, "
                f"{stats.cached} из кэша, {stats.failed} ошибок "
                f"(всего {stats.total})"
            )

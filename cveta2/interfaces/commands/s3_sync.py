"""Implementation of the ``cveta2 s3-sync`` command."""

from typing import TYPE_CHECKING, NamedTuple

from loguru import logger

from cveta2.composition.configuration import (
    CacheConfig,
    ImageCacheConfig,
    images_cache_dir_from,
    optional_global_config,
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
            "Sync only this project (name from image_cache config). If omitted, syncs every configured project."
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


def _sync_target(
    images: ImageCacheConfig, cache: CacheConfig, project_name: str, project_id: int | None = None
) -> SyncTarget | None:
    settings = cache.for_project(project_name, project_id)
    directory = images_cache_dir_from(images, settings, project_name, project_id)
    return SyncTarget(directory, settings.ignored_prefix) if directory is not None else None


def run_s3_sync(args: "argparse.Namespace") -> None:
    """Run the ``s3-sync`` command."""
    if args.root and not args.project:
        raise Cveta2Error("Ошибка: --root требует явного указания проекта через --project.")

    project_filter = args.project.strip() if args.project else None
    failures = _sync_one(project_filter, args.root) if project_filter else _sync_all(args.root)
    if failures:
        raise Cveta2Error("\n".join(failures))


def _sync_one(project_filter: str, sync_root: "str | None") -> list[str]:
    """Sync the explicitly requested project; return its failure, if any."""
    with open_client() as client:
        project_id, project_name, cs_info = resolve_project_and_cloud_storage(
            client, project_filter, sync_root=sync_root
        )
        target = _sync_target(ImageCacheConfig.load(), CacheConfig.load(), project_name, project_id)
        if target is None:
            raise Cveta2Error(
                f"Ошибка: для проекта {project_name!r} не настроен путь "
                f"кэширования изображений.\n"
                f"Добавьте image_cache.{project_name} или cache.images_root "
                f"в конфигурацию (cveta2 setup --images-root PATH или "
                f"cveta2 setup -p <проект> --images-dir PATH)."
            )
        failure = _sync_project(client, project_id, project_name, cs_info, target)
    return [failure] if failure else []


def _sync_all(sync_root: "str | None") -> list[str]:
    """Sync every configured project; return the failures of those that had any."""
    images = ImageCacheConfig.load()
    cache = CacheConfig.load()
    projects_to_sync = sorted(
        name for name in images.projects.keys() | cache.projects.keys() if _sync_target(images, cache, name)
    )
    if not projects_to_sync:
        raise Cveta2Error(
            "Ошибка: нет проектов для синхронизации — не настроены ни "
            "image_cache, ни cache.projects.\n"
            "Добавьте секцию image_cache в конфигурацию или запустите: "
            "cveta2 setup --images-root PATH или cveta2 setup -p <проект> --images-dir PATH"
        )

    shared = optional_global_config()
    synced: set[int] = set()
    skipped: list[str] = []
    failures: list[str] = []
    with open_client() as client:
        for project_name in projects_to_sync:
            logger.info(f"--- Синхронизация проекта: {project_name} ---")
            try:
                definition = shared.projects.get(project_name) if shared else None
                selector = str(definition.id) if definition else project_name
                project_id, live_name, cs_info = resolve_project_and_cloud_storage(
                    client, selector, sync_root=sync_root
                )
            except Cveta2Error as e:
                logger.error(f"Проект {project_name!r}: не удалось определить ID — {e}")
                skipped.append(project_name)
                continue

            if project_id in synced:
                continue
            target = _sync_target(images, cache, live_name, project_id)
            if target is None:
                skipped.append(live_name)
                continue
            synced.add(project_id)
            failure = _sync_project(client, project_id, live_name, cs_info, target)
            if failure is None:
                skipped.append(project_name)
            elif failure:
                failures.append(failure)
    if skipped:
        logger.warning(f"Синхронизация неполная: пропущены проекты {skipped}")
    return failures


def _sync_project(
    client: "CvatClient",
    project_id: int,
    project_name: str,
    cs_info: "CloudStorageInfo | None",
    target: "SyncTarget",
) -> str | None:
    """Sync a resolved project and describe any objects it failed to download.

    Returns None when the project has no cloud storage (skipped), an empty
    string when every object is local, and otherwise the error naming the
    storage and the failed count.  The Python API returns the counters
    unchanged; only the command turns failed objects into a failed run.
    """
    if cs_info is None:
        logger.warning(f"Проект {project_name!r}: cloud storage не найден — пропускаем.")
        return None
    stats = client.sync_project_images(
        project_id,
        target.cache_dir,
        project_cloud_storage=cs_info,
        ignored_prefix=target.ignored_prefix,
    )
    logger.info(f"Проект {project_name!r}: {stats.summary()}")
    if not stats.failed:
        return ""
    return (
        f"Ошибка: проект {project_name!r}: не удалось скачать {stats.failed} из {stats.total} "
        f"объектов из s3://{cs_info.bucket}/{cs_info.prefix}. Повторите s3-sync: "
        "скачанные файлы будут пропущены."
    )

"""Resolve settings and assemble production workflow dependencies."""

import threading
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path

from loguru import logger

from cveta2.adapters.class_api.http import HttpClassApi
from cveta2.adapters.config.settings import (
    CacheConfig,
    IgnoreConfig,
    SyncRootsConfig,
    is_cache_disabled,
    resolve_images_cache_dir,
)
from cveta2.adapters.execution.concurrency import Workers, run_concurrent
from cveta2.adapters.files.bundle import LocalBundleFiles
from cveta2.adapters.files.manifests import LocalManifestStore
from cveta2.adapters.files.task_output import LocalWorkflowFiles
from cveta2.adapters.s3.task_cache import AnnotationCacheFactory
from cveta2.adapters.s3.upload import S3UploadStorage
from cveta2.application.client import ApplicationClient
from cveta2.application.ports.cache import CacheInvalidator
from cveta2.application.use_cases import fetch, resolve, task_ops, upload
from cveta2.application.use_cases.fetch_draft import DraftServices, write_fetch_draft
from cveta2.composition.configuration import project_publication
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import ProjectAnnotations, TaskInfo
from cveta2.domain.partition import PartitionResult
from cveta2.domain.storage import CloudStorageInfo


def fetch_dependencies(target: fetch.FetchTarget, options: fetch.FetchOptions) -> fetch.FetchDependencies:
    """Resolve settings and assemble fetch effect dependencies."""
    return fetch.FetchDependencies(
        caches=AnnotationCacheFactory(),
        files=LocalWorkflowFiles(),
        runner=run_concurrent,
        clock=time.monotonic,
        lock_factory=threading.Lock,
        cache_settings=CacheConfig.load(options.config_path).for_project(target.project_name),
        cache_enabled=not is_cache_disabled(),
        cvat_workers=Workers.cvat,
    )


def fetch_project(client: ApplicationClient, target: fetch.FetchTarget, options: fetch.FetchOptions) -> PartitionResult:
    """Run a project fetch using configured production adapters, then write its draft ``dataset.yaml``.

    The publication settings are read before the fetch, so a broken
    configuration stops it before any CVAT work. The draft step only warns.
    """
    publication = project_publication(target.project_id, config_path=options.config_path)
    partition = fetch.fetch_project(client, target, options, deps=fetch_dependencies(target, options))
    write_fetch_draft(
        target.output_dir,
        partition.dataset,
        project_name=target.project_name,
        publication=publication,
        storage=target.cs_info,
        images_dir=options.images_dir,
        services=DraftServices(LocalBundleFiles(), HttpClassApi()),
    )
    return partition


def fetch_selected_tasks(
    client: ApplicationClient, target: fetch.FetchTarget, options: fetch.FetchOptions
) -> ProjectAnnotations:
    """Fetch selected tasks using configured production adapters."""
    return fetch.fetch_selected_tasks(client, target, options, deps=fetch_dependencies(target, options))


def load_ignore_sets(project_name: str, config_path: Path | None = None) -> tuple[set[int] | None, set[int] | None]:
    """Resolve ignored and silent task IDs from project configuration."""
    ignore_cfg = IgnoreConfig.load(config_path)
    ignored_ids = ignore_cfg.get_ignored_tasks(project_name)
    if not ignored_ids:
        return None, None
    silent_ids = ignore_cfg.get_silent_task_ids(project_name)
    return set(ignored_ids), silent_ids or None


def invalidate_local_entry(
    project_id: int,
    task_id: int,
    project_name: str,
    cs_info: CloudStorageInfo | None = None,
    *,
    config_path: Path | None = None,
) -> None:
    """Invalidate local state and the enabled remote cache mirror.

    *config_path* selects the configuration file whose cache settings name
    the entry, the same file a fetch with that path writes through.
    It runs after a successful remote write, so expected failures warn and
    never raise: a broken mirror still drops the local entry.
    """
    try:
        settings = CacheConfig.load(config_path).for_project(project_name)
    except (Cveta2Error, OSError) as error:
        logger.warning(f"Кэш задачи {task_id} не очищен: не удалось прочитать настройки кэша ({error}).")
        return
    factory = AnnotationCacheFactory()
    try:
        cache = factory.create(project_id, cs_info, settings, local_only=is_cache_disabled())
    except Cveta2Error as error:
        logger.warning(f"S3-кэш задачи {task_id} не очищен: {error} — очищен только локальный кэш.")
        cache = factory.create(project_id, None, settings, local_only=True)
    cache.invalidate(task_id)


def _cache_invalidator(config_path: Path | None) -> CacheInvalidator:
    """Bind cache invalidation to the selected configuration file."""
    if config_path is None:
        return invalidate_local_entry
    return partial(invalidate_local_entry, config_path=config_path)


def upload_dependencies(
    *, config_path: Path | None = None, sleep: Callable[[float], None] = time.sleep
) -> upload.UploadDependencies:
    """Assemble production upload staging and recovery dependencies."""
    return upload.UploadDependencies(
        storage=S3UploadStorage(),
        files=LocalWorkflowFiles(),
        manifests=LocalManifestStore(),
        invalidate=_cache_invalidator(config_path),
        sleep=sleep,
    )


def upload_cvat_dataset(
    client: ApplicationClient, request: upload.UploadRequest, *, config_path: Path | None = None
) -> upload.UploadOutcome:
    """Run an upload using configured production adapters."""
    return upload.upload_dataset(client, request, deps=upload_dependencies(config_path=config_path))


def read_exclude_names(in_progress_path: str | None) -> set[str]:
    """Read excluded frame names from the optional CSV."""
    return upload.read_exclude_names(in_progress_path, files=LocalWorkflowFiles())


def build_search_dirs(
    image_dirs: Sequence[str | Path] | str | Path | None,
    project_name: str,
    *,
    config_path: Path | None = None,
) -> list[Path]:
    """Resolve explicit and configured local image search roots."""
    if isinstance(image_dirs, (str, Path)):
        image_dirs = [image_dirs]
    resolved = [Path(directory).resolve() for directory in image_dirs or []]
    return upload.build_search_dirs(
        resolved,
        project_name,
        cache_dir=resolve_images_cache_dir(project_name, config_path),
    )


def project_cloud_storage(
    client: ApplicationClient,
    project_id: int,
    project_name: str,
    root: str | None = None,
    *,
    config_path: Path | None = None,
) -> CloudStorageInfo | None:
    """Resolve project storage and configured sync-root overrides."""
    configured_root = None if root else SyncRootsConfig.load(config_path).get_root(project_name)
    return resolve.project_cloud_storage(client, project_id, project_name, root, configured_root=configured_root)


def apply_sync_root_override(
    project_name: str,
    cs_info: CloudStorageInfo | None,
    explicit_root: str | None = None,
    *,
    config_path: Path | None = None,
) -> CloudStorageInfo | None:
    """Apply explicit or configured project storage root policy."""
    configured_root = None if explicit_root else SyncRootsConfig.load(config_path).get_root(project_name)
    return resolve.apply_sync_root_override(project_name, cs_info, explicit_root, configured_root=configured_root)


def resolved_task(
    client: ApplicationClient,
    project_id: int,
    project_name: str,
    task: int | str,
    *,
    config_path: Path | None = None,
) -> AbstractContextManager[TaskInfo]:
    """Resolve a task and invalidate its cache, as *config_path* selects it, on exit."""
    return task_ops.resolved_task(client, project_id, project_name, task, invalidate=_cache_invalidator(config_path))

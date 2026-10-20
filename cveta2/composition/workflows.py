"""Resolve settings and assemble production workflow dependencies."""

import threading
import time
from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path

from cveta2.adapters.config.settings import (
    CacheConfig,
    IgnoreConfig,
    SyncRootsConfig,
    is_cache_disabled,
    resolve_images_cache_dir,
)
from cveta2.adapters.execution.concurrency import Workers, run_concurrent
from cveta2.adapters.files.manifests import LocalManifestStore
from cveta2.adapters.files.task_output import LocalWorkflowFiles
from cveta2.adapters.s3.task_cache import AnnotationCacheFactory
from cveta2.adapters.s3.upload import S3UploadStorage
from cveta2.application.client import ApplicationClient
from cveta2.application.use_cases import fetch, resolve, task_ops, upload
from cveta2.domain.models import ProjectAnnotations, TaskInfo
from cveta2.domain.partition import PartitionResult
from cveta2.domain.storage import CloudStorageInfo


def fetch_dependencies(
    target: fetch.FetchTarget, options: fetch.FetchOptions
) -> fetch.FetchDependencies:
    """Resolve settings and assemble fetch effect dependencies."""
    return fetch.FetchDependencies(
        caches=AnnotationCacheFactory(),
        files=LocalWorkflowFiles(),
        runner=run_concurrent,
        clock=time.monotonic,
        lock_factory=threading.Lock,
        cache_settings=CacheConfig.load(options.config_path).for_project(
            target.project_name
        ),
        cache_enabled=not is_cache_disabled(),
        cvat_workers=Workers.cvat,
    )


def fetch_project(
    client: ApplicationClient, target: fetch.FetchTarget, options: fetch.FetchOptions
) -> PartitionResult:
    """Run a project fetch using configured production adapters."""
    return fetch.fetch_project(
        client, target, options, deps=fetch_dependencies(target, options)
    )


def fetch_selected_tasks(
    client: ApplicationClient, target: fetch.FetchTarget, options: fetch.FetchOptions
) -> ProjectAnnotations:
    """Fetch selected tasks using configured production adapters."""
    return fetch.fetch_selected_tasks(
        client, target, options, deps=fetch_dependencies(target, options)
    )


def load_ignore_sets(
    project_name: str, config_path: Path | None = None
) -> tuple[set[int] | None, set[int] | None]:
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
) -> None:
    """Invalidate local state and the enabled remote cache mirror."""
    settings = CacheConfig.load().for_project(project_name)
    cache = AnnotationCacheFactory().create(
        project_id, cs_info, settings, local_only=is_cache_disabled()
    )
    cache.invalidate(task_id)


def upload_dependencies() -> upload.UploadDependencies:
    """Assemble production upload staging and recovery dependencies."""
    return upload.UploadDependencies(
        storage=S3UploadStorage(),
        files=LocalWorkflowFiles(),
        manifests=LocalManifestStore(),
        invalidate=invalidate_local_entry,
    )


def upload_cvat_dataset(
    client: ApplicationClient, request: upload.UploadRequest
) -> upload.UploadOutcome:
    """Run an upload using configured production adapters."""
    return upload.upload_dataset(client, request, deps=upload_dependencies())


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
    configured_root = (
        None if root else SyncRootsConfig.load(config_path).get_root(project_name)
    )
    return resolve.project_cloud_storage(
        client, project_id, project_name, root, configured_root=configured_root
    )


def apply_sync_root_override(
    project_name: str,
    cs_info: CloudStorageInfo | None,
    explicit_root: str | None = None,
    *,
    config_path: Path | None = None,
) -> CloudStorageInfo | None:
    """Apply explicit or configured project storage root policy."""
    configured_root = (
        None
        if explicit_root
        else SyncRootsConfig.load(config_path).get_root(project_name)
    )
    return resolve.apply_sync_root_override(
        project_name, cs_info, explicit_root, configured_root=configured_root
    )


def resolved_task(
    client: ApplicationClient, project_id: int, project_name: str, task: int | str
) -> AbstractContextManager[TaskInfo]:
    """Resolve a task and invalidate its cache on context exit."""
    return task_ops.resolved_task(
        client, project_id, project_name, task, invalidate=invalidate_local_entry
    )

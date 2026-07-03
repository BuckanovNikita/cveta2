"""Fetch pipeline orchestration: cache loop, per-task CSVs, download, outputs.

Pure orchestration over :class:`CvatClient` — no prompts, no ``sys.exit``.
The CLI layer resolves interactive inputs (project, task selector, image
directory) before calling in; the public API calls in directly.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger
from tqdm import tqdm

from cveta2.config import is_cache_disabled, load_ignore_config
from cveta2.dataset_partition import partition_annotations_df
from cveta2.models import TaskAnnotations
from cveta2.services.output import (
    populate_record_paths,
    write_dataset_and_deleted,
    write_partition_csvs,
    write_raw_csv,
)
from cveta2.task_cache import (
    S3CacheBackend,
    TaskAnnotationCache,
    get_task_cache_dir,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.client import CvatClient, FetchContext
    from cveta2.dataset_partition import PartitionResult
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import ProjectAnnotations


@dataclass(frozen=True)
class FetchOptions:
    """Options for the fetch pipeline (all inputs already resolved)."""

    completed_only: bool = False
    task_selector: list[int | str] | None = None
    ignore_task_ids: set[int] | None = None
    silent_task_ids: set[int] | None = None
    use_cache: bool = True
    force: bool = False
    save_tasks: bool = False
    images_dir: Path | None = None
    raw: bool = False
    publish_clearml: bool = True


def load_ignore_sets(
    project_name: str,
) -> tuple[set[int] | None, set[int] | None]:
    """Load ignore config, return ``(ignore_set, silent_set)``.

    *ignore_set* contains all ignored task IDs (or None if empty).
    *silent_set* contains IDs of tasks marked ``silent=True``.
    """
    ignore_cfg = load_ignore_config()
    ignored_ids = ignore_cfg.get_ignored_tasks(project_name)
    if not ignored_ids:
        return None, None
    silent_ids = ignore_cfg.get_silent_task_ids(project_name)
    return set(ignored_ids), (silent_ids or None)


def fetch_project(  # noqa: PLR0913
    client: CvatClient,
    project_id: int,
    project_name: str,
    output_dir: Path,
    cs_info: CloudStorageInfo | None,
    options: FetchOptions,
) -> PartitionResult:
    """Full-project fetch: partition outputs, optional raw.csv, ClearML publish.

    Writes dataset/obsolete/in_progress/deleted CSVs (plus raw.csv when
    ``options.raw``) into *output_dir* and returns the partition.
    """
    result = _fetch_core(
        client,
        project_id,
        project_name,
        output_dir,
        cs_info,
        options,
        prune_cache=True,
    )

    if options.raw:
        write_raw_csv(result, output_dir)

    df = pd.DataFrame(result.to_csv_rows())
    partition = partition_annotations_df(df, result.deleted_images)
    write_partition_csvs(partition, output_dir)

    if options.publish_clearml:
        from cveta2._clearml import maybe_publish_clearml  # noqa: PLC0415

        maybe_publish_clearml(project_name, output_dir)

    return partition


def fetch_selected_tasks(  # noqa: PLR0913
    client: CvatClient,
    project_id: int,
    project_name: str,
    output_dir: Path,
    cs_info: CloudStorageInfo | None,
    options: FetchOptions,
) -> ProjectAnnotations:
    """Selected-tasks fetch: writes dataset.csv + deleted.csv, returns result."""
    result = _fetch_core(
        client,
        project_id,
        project_name,
        output_dir,
        cs_info,
        options,
        prune_cache=False,
    )
    write_dataset_and_deleted(result, output_dir)
    return result


def _fetch_core(  # noqa: PLR0913
    client: CvatClient,
    project_id: int,
    project_name: str,
    output_dir: Path,
    cs_info: CloudStorageInfo | None,
    options: FetchOptions,
    *,
    prune_cache: bool,
) -> ProjectAnnotations:
    """Shared fetch flow: prepare, cache loop, prune, download, path population."""
    ctx = client.prepare_fetch(
        project_id,
        completed_only=options.completed_only,
        ignore_task_ids=options.ignore_task_ids,
        silent_task_ids=options.silent_task_ids,
        task_selector=options.task_selector,
        project_name=project_name,
    )

    cache = _build_task_cache(client, project_id, options)

    result = _fetch_and_save_tasks(
        client,
        ctx,
        output_dir,
        save_tasks=options.save_tasks,
        cache=cache,
        force=options.force,
    )

    if cache is not None and prune_cache:
        live_ids = {t.id for t in client.list_project_tasks(project_id)}
        pruned = cache.prune(live_ids)
        if pruned:
            logger.info(f"Кэш аннотаций: удалено устаревших записей: {pruned}")

    if options.images_dir is not None:
        stats = client.download_images(
            result,
            options.images_dir,
            project_id=project_id,
            project_cloud_storage=cs_info,
        )
        logger.info(
            f"Изображения: {stats.downloaded} загружено, "
            f"{stats.cached} из кэша, {stats.failed} ошибок"
        )
    populate_record_paths(result, cs_info, options.images_dir)

    return result


def _build_task_cache(
    client: CvatClient,
    project_id: int,
    options: FetchOptions,
) -> TaskAnnotationCache | None:
    """Build the task-annotation cache for a fetch run.

    ``use_cache=False`` (``--no-cache``) or ``CVETA2_DISABLE_CACHE=true``
    disables caching entirely.  The S3 backend always uses the project's
    original CVAT cloud storage prefix (never a user override), so all
    users share one cache location.
    """
    if not options.use_cache or is_cache_disabled():
        return None
    s3_backend = S3CacheBackend.from_cloud_storage(
        client.detect_project_cloud_storage(project_id)
    )
    return TaskAnnotationCache(get_task_cache_dir(project_id), s3=s3_backend)


def _fetch_and_save_tasks(  # noqa: PLR0913
    client: CvatClient,
    ctx: FetchContext,
    output_dir: Path,
    *,
    save_tasks: bool = False,
    cache: TaskAnnotationCache | None = None,
    force: bool = False,
) -> ProjectAnnotations:
    """Fetch tasks one by one, saving per-task CSVs into ``output_dir/.tasks/``.

    Completed tasks are served from *cache* when possible; fresh results
    are cached before any path population so shared S3 entries stay
    machine-independent.  With *force* the cache is only written, never
    read.  When *save_tasks* is False (default), the ``.tasks/``
    directory is removed after merging.

    Returns the merged :class:`ProjectAnnotations` from all fetched tasks.
    """
    if not ctx.tasks:
        logger.warning("No tasks in this project.")
        return TaskAnnotations.merge([])

    tasks_dir = output_dir / ".tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    cache_hits = 0
    fetched = 0
    task_results: list[TaskAnnotations] = []
    api = client.api
    for task in tqdm(ctx.tasks, desc="Processing tasks", unit="task", leave=False):
        task_result = None if force or cache is None else cache.get(task)
        if task_result is not None:
            cache_hits += 1
        else:
            task_result = client.fetch_one_task(api, task, ctx)
            if task_result is None:
                continue
            fetched += 1
            if cache is not None:
                cache.put(task, task_result)

        rows = task_result.to_csv_rows()
        if rows:
            df = pd.DataFrame(rows)
            task_csv = tasks_dir / f"task_{task.id}.csv"
            df.to_csv(task_csv, index=False, encoding="utf-8")
            logger.trace(
                f"Task {task.name!r} (id={task.id}): {len(rows)} rows → {task_csv}"
            )

        task_results.append(task_result)

    if not save_tasks:
        shutil.rmtree(tasks_dir, ignore_errors=True)

    if cache is not None:
        logger.info(f"Задач из кэша: {cache_hits}, загружено с CVAT: {fetched}")

    return TaskAnnotations.merge(task_results)

"""Fetch pipeline orchestration: cache loop, per-task CSVs, download, outputs.

Pure orchestration over :class:`CvatClient` — no prompts, no ``sys.exit``.
The CLI layer resolves interactive inputs (project, task selector, image
directory) before calling in; the public API calls in directly.
"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2._concurrency import Workers, run_concurrent
from cveta2.config import CacheConfig, IgnoreConfig, is_cache_disabled
from cveta2.dataset_partition import partition_annotations_df
from cveta2.models import TaskAnnotations
from cveta2.services.output import (
    CSV_WRITE_OPTIONS,
    format_counts,
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
    from cveta2.config import CacheProjectSettings
    from cveta2.dataset_partition import PartitionResult
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import ProjectAnnotations, TaskInfo


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
    config_path: Path | None = None


def load_ignore_sets(
    project_name: str,
    config_path: Path | None = None,
) -> tuple[set[int] | None, set[int] | None]:
    """Load ignore config, return ``(ignore_set, silent_set)``.

    *ignore_set* contains all ignored task IDs (or None if empty).
    *silent_set* contains IDs of tasks marked ``silent=True``.
    """
    ignore_cfg = IgnoreConfig.load(config_path)
    ignored_ids = ignore_cfg.get_ignored_tasks(project_name)
    if not ignored_ids:
        return None, None
    silent_ids = ignore_cfg.get_silent_task_ids(project_name)
    return set(ignored_ids), (silent_ids or None)


def fetch_project(  # noqa: PLR0913, PLR0917
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

    started = time.monotonic()
    df = pd.DataFrame(result.to_csv_rows())
    partition = partition_annotations_df(df, result.deleted_images)
    write_partition_csvs(partition, output_dir)
    logger.info(f"Партиционирование и запись CSV: {time.monotonic() - started:.1f} с")

    if options.publish_clearml:
        from cveta2._clearml import maybe_publish_clearml  # noqa: PLC0415

        maybe_publish_clearml(project_name, output_dir)

    return partition


def fetch_selected_tasks(  # noqa: PLR0913, PLR0917
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


def _fetch_core(  # noqa: PLR0913, PLR0917
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
    started = time.monotonic()
    ctx = client.prepare_fetch(
        project_id,
        completed_only=options.completed_only,
        ignore_task_ids=options.ignore_task_ids,
        silent_task_ids=options.silent_task_ids,
        task_selector=options.task_selector,
        project_name=project_name,
    )
    logger.debug(
        f"Отбор задач: {len(ctx.tasks)} к загрузке ({time.monotonic() - started:.1f} с)"
    )

    cache_settings = CacheConfig.load(options.config_path).for_project(project_name)
    cache = _build_task_cache(client, project_id, options, cache_settings)
    policy = _CachePolicy(cache=cache, force=options.force)

    result = _fetch_and_save_tasks(
        client,
        ctx,
        output_dir,
        policy,
        save_tasks=options.save_tasks,
    )

    if cache is not None and prune_cache:
        live_ids = {t.id for t in client.list_project_tasks(project_id)}
        pruned = cache.prune(live_ids)
        if pruned:
            logger.info(f"Кэш аннотаций: удалено устаревших записей: {pruned}")

    if options.images_dir is not None:
        started = time.monotonic()
        stats = client.download_images(
            result,
            options.images_dir,
            project_id=project_id,
            project_cloud_storage=cs_info,
            ignored_prefix=cache_settings.ignored_prefix,
        )
        logger.info(
            f"Изображения: {stats.downloaded} загружено, "
            f"{stats.cached} из кэша, {stats.failed} ошибок "
            f"({time.monotonic() - started:.1f} с)"
        )
    populate_record_paths(
        result,
        cs_info,
        options.images_dir,
        ignored_prefix=cache_settings.ignored_prefix,
    )

    return result


def _build_task_cache(
    client: CvatClient,
    project_id: int,
    options: FetchOptions,
    cache_settings: CacheProjectSettings,
) -> TaskAnnotationCache | None:
    """Build the task-annotation cache for a fetch run.

    ``use_cache=False`` (``--no-cache``) or ``CVETA2_DISABLE_CACHE=true``
    disables caching entirely.  The S3 backend uses the project's CVAT
    cloud storage prefix (never a sync-root override) unless the
    ``cache.projects.<name>.task_cache_s3`` setting points elsewhere, so
    all users share one cache location.
    """
    if not options.use_cache or is_cache_disabled():
        return None
    s3_backend = S3CacheBackend.from_cloud_storage(
        client.detect_project_cloud_storage(project_id),
        task_cache_s3=cache_settings.task_cache_s3,
    )
    local_dir = get_task_cache_dir(project_id, root=cache_settings.tasks_root)
    return TaskAnnotationCache(local_dir, s3=s3_backend)


@dataclass(frozen=True)
class _CachePolicy:
    """How the fetch loop uses the task-annotation cache."""

    cache: TaskAnnotationCache | None = None
    force: bool = False

    def read(self, task: TaskInfo) -> TaskAnnotations | None:
        """Return a cached result, or None when reading is disabled/absent."""
        if self.force or self.cache is None:
            return None
        return self.cache.get(task)

    def write(self, task: TaskInfo, result: TaskAnnotations) -> None:
        if self.cache is not None:
            self.cache.put(task, result)


@dataclass
class _FetchStats:
    """Cache-hit vs live-fetch counts and elapsed seconds for the fetch loop.

    Several tasks are fetched at once, so the counters are shared across
    threads and every update goes through the lock: a bare ``+=`` is a
    read-modify-write and would lose totals under contention.
    """

    cache_hits: int = 0
    fetched: int = 0
    hit_seconds: float = 0.0
    fetch_seconds: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_hit(self, seconds: float) -> None:
        with self.lock:
            self.cache_hits += 1
            self.hit_seconds += seconds

    def record_fetch(self, seconds: float) -> None:
        with self.lock:
            self.fetched += 1
            self.fetch_seconds += seconds

    def log_summary(self) -> None:
        logger.info(
            f"Задач из кэша: {self.cache_hits} ({self.hit_seconds:.1f} с), "
            f"загружено с CVAT: {self.fetched} ({self.fetch_seconds:.1f} с)"
        )


def _retrieve_task(
    client: CvatClient,
    task: TaskInfo,
    ctx: FetchContext,
    policy: _CachePolicy,
    stats: _FetchStats,
) -> TaskAnnotations | None:
    """Return a task's annotations from cache or a live fetch, updating *stats*.

    Returns ``None`` when a live fetch skipped the task (5xx).  Fresh
    results are cached before path population so shared S3 entries stay
    machine-independent.
    """
    started = time.monotonic()
    cached = policy.read(task)
    if cached is not None:
        stats.record_hit(time.monotonic() - started)
        return cached

    fetched = client.fetch_one_task(client.api, task, ctx)
    if fetched is None:
        return None
    policy.write(task, fetched)
    stats.record_fetch(time.monotonic() - started)
    return fetched


def _write_task_csv(task: TaskInfo, result: TaskAnnotations, tasks_dir: Path) -> None:
    """Write one task's rows to ``tasks_dir/task_<id>.csv`` (skips empty results)."""
    rows = result.to_csv_rows()
    if not rows:
        return
    task_csv = tasks_dir / f"task_{task.id}.csv"
    task_df = pd.DataFrame(rows)
    task_df.to_csv(task_csv, **CSV_WRITE_OPTIONS)
    logger.trace(
        f"Task {task.name!r} (id={task.id}): {format_counts(task_df)} → {task_csv}"
    )


def _fetch_and_save_tasks(
    client: CvatClient,
    ctx: FetchContext,
    output_dir: Path,
    policy: _CachePolicy,
    *,
    save_tasks: bool,
) -> ProjectAnnotations:
    """Fetch tasks in parallel, saving per-task CSVs into ``output_dir/.tasks/``.

    Up to ``Workers.cvat`` tasks are in flight at once; each is a handful
    of CVAT round-trips that spend nearly all their time waiting.  Results are
    returned in task order regardless of completion order, so the merged
    output does not depend on which task happened to finish first.

    Completed tasks are served from *policy*'s cache when possible.  Unless
    *save_tasks* is set, the ``.tasks/`` directory is removed after merging —
    best effort, since a leftover tree from an earlier run may belong to
    another user of a shared output directory.

    Returns the merged :class:`ProjectAnnotations` from all fetched tasks.
    """
    if not ctx.tasks:
        logger.warning("No tasks in this project.")
        return TaskAnnotations.merge([])

    tasks_dir = output_dir / ".tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    stats = _FetchStats()

    def process(task: TaskInfo) -> TaskAnnotations | None:
        result = _retrieve_task(client, task, ctx, policy, stats)
        if result is not None:
            _write_task_csv(task, result, tasks_dir)
        return result

    # catch=(): a failure that got this far is already past the retry budget
    # and the 5xx skip, so it aborts the fetch exactly as it did serially.
    outcomes = run_concurrent(
        ctx.tasks,
        process,
        max_workers=Workers.cvat,
        catch=(),
        desc="Processing tasks",
        unit="task",
    )
    task_results = [r for r in outcomes if isinstance(r, TaskAnnotations)]

    if not save_tasks:
        shutil.rmtree(tasks_dir, ignore_errors=True)

    if policy.cache is not None:
        stats.log_summary()

    return TaskAnnotations.merge(task_results)

"""Fetch pipeline orchestration: cache loop, per-task CSVs, download, outputs.

Pure orchestration over :class:`CvatClient` — no prompts, no ``sys.exit``.
The CLI layer resolves interactive inputs (project, task selector, image
directory) before calling in; the public API calls in directly.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from loguru import logger

from cveta2.application.client import ApplicationClient as CvatClient
from cveta2.application.client.shared import FetchContext
from cveta2.application.ports.cache import CacheFactory, TaskCache
from cveta2.application.ports.execution import ConcurrentRunner
from cveta2.application.ports.publisher import DatasetPublisher
from cveta2.application.ports.workflow_files import FetchFiles
from cveta2.application.settings import CacheProjectSettings
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import (
    CSV_COLUMNS,
    ProjectAnnotations,
    TaskAnnotations,
    TaskInfo,
)
from cveta2.domain.partition import PartitionResult, partition_annotations_df
from cveta2.domain.storage import CloudStorageInfo


@dataclass(frozen=True)
class FetchDependencies:
    """Resolved policies and outgoing effects for a fetch invocation."""

    caches: CacheFactory
    files: FetchFiles
    runner: ConcurrentRunner
    clock: Callable[[], float]
    lock_factory: Callable[[], AbstractContextManager[object]]
    cache_settings: CacheProjectSettings
    publisher: DatasetPublisher | None = None
    cache_enabled: bool = True
    cvat_workers: int = 1


@dataclass(frozen=True)
class FetchTarget:
    """What a fetch runs against: the project, and where its output goes.

    Separate from :class:`FetchOptions`, which carries how the fetch
    behaves. The four fields travel together through every function in
    this module, so passing them individually was what made the
    signatures wide.
    """

    project_id: int
    project_name: str
    output_dir: Path
    cs_info: CloudStorageInfo | None = None


@dataclass(frozen=True)
class FetchOptions:
    """Options for the fetch pipeline (all inputs already resolved)."""

    completed_only: bool = False
    skip_validation: bool = False
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


def fetch_project(
    client: CvatClient,
    target: FetchTarget,
    options: FetchOptions,
    *,
    deps: FetchDependencies,
) -> PartitionResult:
    """Full-project fetch: partition outputs, optional raw.csv, ClearML publish.

    Writes dataset/obsolete/in_progress/deleted CSVs (plus raw.csv when
    ``options.raw``) into ``target.output_dir`` and returns the partition.
    """
    output_dir = target.output_dir
    if options.skip_validation:
        _promote_completed_annotations(client, target, options, deps=deps)
    result = _fetch_core(client, target, options, prune_cache=True, deps=deps)

    if options.raw:
        deps.files.write_raw_csv(result, output_dir)

    started = deps.clock()
    df = pd.DataFrame(result.to_csv_rows(), columns=list(CSV_COLUMNS))
    partition = partition_annotations_df(df, result.deleted_images)
    deps.files.write_partition_csvs(partition, output_dir)
    logger.info(f"Партиционирование и запись CSV: {deps.clock() - started:.1f} с")

    if options.publish_clearml and deps.publisher is not None:
        deps.publisher(target.project_name, output_dir)

    return partition


def _promote_completed_annotations(
    client: CvatClient,
    target: FetchTarget,
    options: FetchOptions,
    *,
    deps: FetchDependencies,
) -> None:
    """Accept eligible tasks before normal fetch applies completion filtering."""
    try:
        tasks = client.list_project_tasks(target.project_id)
    except Cveta2Error as error:
        raise Cveta2Error(
            f"Не удалось получить задачи проекта {target.project_id}: {error}"
        ) from error
    tasks = [t for t in tasks if t.id not in (options.ignore_task_ids or set())]
    settings = deps.cache_settings
    cache = _build_task_cache(client, target.project_id, options, settings, deps=deps)
    if cache is None:
        # Disabled caching still leaves old local entries from earlier runs.
        cache = deps.caches.create(target.project_id, None, settings, local_only=True)

    def promote(task: TaskInfo) -> None:
        """Perform the declared workflow operation."""
        _promote_task(client, task, cache)

    # Propagate failures after waiting for in-flight workers; no fetch or output
    # may start until the entire promotion phase succeeds.
    deps.runner(
        tasks,
        promote,
        max_workers=deps.cvat_workers,
        catch=(),
        desc="Accepting completed annotations",
        unit="task",
    )


def _promote_task(
    client: CvatClient,
    task: TaskInfo,
    cache: TaskCache,
) -> None:
    """Check every job and invalidate before the first sequential mutation."""
    try:
        jobs = client.api.get_task_jobs(task.id)
    except Cveta2Error as error:
        raise Cveta2Error(
            f"Не удалось получить jobs задачи {task.id}: {error}"
        ) from error
    if not jobs or any(
        job.state != "completed" or job.stage not in {"annotation", "acceptance"}
        for job in jobs
    ):
        return
    pending = [job for job in jobs if job.stage == "annotation"]
    if not pending:
        return
    try:
        # Strict pre-invalidation keeps a partial PATCH failure retryable even
        # when CVAT leaves updated_date unchanged. A failed delete precedes writes.
        cache.invalidate(task.id, strict=True)
    except (Cveta2Error, OSError) as error:
        raise Cveta2Error(
            f"Не удалось очистить кэш задачи {task.id}: {error}"
        ) from error
    try:
        for job in pending:
            client.api.update_job(job.id, stage="acceptance", state="completed")
    except Cveta2Error as error:
        raise Cveta2Error(
            f"Не удалось принять job {job.id} задачи {task.id}: {error}"
        ) from error


def fetch_selected_tasks(
    client: CvatClient,
    target: FetchTarget,
    options: FetchOptions,
    *,
    deps: FetchDependencies,
) -> ProjectAnnotations:
    """Selected-tasks fetch: writes dataset.csv + deleted.csv, returns result."""
    result = _fetch_core(client, target, options, prune_cache=False, deps=deps)
    deps.files.write_dataset_and_deleted(result, target.output_dir)
    return result


def _fetch_core(
    client: CvatClient,
    target: FetchTarget,
    options: FetchOptions,
    *,
    deps: FetchDependencies,
    prune_cache: bool,
) -> ProjectAnnotations:
    """Shared fetch flow: prepare, cache loop, prune, download, path population."""
    project_id, project_name = target.project_id, target.project_name
    started = deps.clock()
    ctx = client.prepare_fetch(
        project_id,
        completed_only=options.completed_only,
        ignore_task_ids=options.ignore_task_ids,
        silent_task_ids=options.silent_task_ids,
        task_selector=options.task_selector,
        project_name=project_name,
    )
    logger.debug(
        f"Отбор задач: {len(ctx.tasks)} к загрузке ({deps.clock() - started:.1f} с)"
    )

    cache_settings = deps.cache_settings
    cache = _build_task_cache(client, project_id, options, cache_settings, deps=deps)
    policy = _CachePolicy(cache=cache, force=options.force)

    result = _fetch_and_save_tasks(
        client,
        ctx,
        target.output_dir,
        policy,
        save_tasks=options.save_tasks,
        deps=deps,
    )

    if cache is not None and prune_cache:
        live_ids = {t.id for t in client.list_project_tasks(project_id)}
        pruned = cache.prune(live_ids)
        if pruned:
            logger.info(f"Кэш аннотаций: удалено устаревших записей: {pruned}")

    if options.images_dir is not None:
        started = deps.clock()
        stats = client.download_images(
            result,
            options.images_dir,
            project_id=project_id,
            project_cloud_storage=target.cs_info,
            ignored_prefix=cache_settings.ignored_prefix,
        )
        logger.info(f"Изображения: {stats.summary()} ({deps.clock() - started:.1f} с)")
    deps.files.populate_record_paths(
        result,
        target.cs_info,
        options.images_dir,
        ignored_prefix=cache_settings.ignored_prefix,
    )

    return result


def _build_task_cache(
    client: CvatClient,
    project_id: int,
    options: FetchOptions,
    cache_settings: CacheProjectSettings,
    *,
    deps: FetchDependencies,
) -> TaskCache | None:
    """Build the task-annotation cache for a fetch run.

    ``use_cache=False`` (``--no-cache``) or ``CVETA2_DISABLE_CACHE=true``
    disables caching entirely.  The S3 backend uses the project's CVAT
    cloud storage prefix (never a sync-root override) unless the
    ``cache.projects.<name>.task_cache_s3`` setting points elsewhere, so
    all users share one cache location.
    """
    if not options.use_cache or not deps.cache_enabled:
        return None
    return deps.caches.create(
        project_id, client.detect_project_cloud_storage(project_id), cache_settings
    )


@dataclass(frozen=True)
class _CachePolicy:
    """How the fetch loop uses the task-annotation cache."""

    cache: TaskCache | None = None
    force: bool = False

    def read(self, task: TaskInfo) -> TaskAnnotations | None:
        """Return a cached result, or None when reading is disabled/absent."""
        if self.force or self.cache is None:
            return None
        return self.cache.get(task)

    def write(self, task: TaskInfo, result: TaskAnnotations) -> None:
        """Perform the declared workflow operation."""
        if self.cache is not None:
            self.cache.put(task, result)


@dataclass
class _FetchStats:
    """Cache-hit vs live-fetch counts and elapsed seconds for the fetch loop.

    Several tasks are fetched at once, so the counters are shared across
    threads and every update goes through the lock: a bare ``+=`` is a
    read-modify-write and would lose totals under contention.
    """

    lock: AbstractContextManager[object] = field(repr=False)
    cache_hits: int = 0
    fetched: int = 0
    hit_seconds: float = 0.0
    fetch_seconds: float = 0.0

    def record_hit(self, seconds: float) -> None:
        """Perform the declared workflow operation."""
        with self.lock:
            self.cache_hits += 1
            self.hit_seconds += seconds

    def record_fetch(self, seconds: float) -> None:
        """Perform the declared workflow operation."""
        with self.lock:
            self.fetched += 1
            self.fetch_seconds += seconds

    def log_summary(self) -> None:
        """Perform the declared workflow operation."""
        logger.info(
            f"Задач из кэша: {self.cache_hits} ({self.hit_seconds:.1f} с), "
            f"загружено с CVAT: {self.fetched} ({self.fetch_seconds:.1f} с)"
        )


def _retrieve_task(  # noqa: PLR0913
    client: CvatClient,
    task: TaskInfo,
    ctx: FetchContext,
    policy: _CachePolicy,
    stats: _FetchStats,
    *,
    deps: FetchDependencies,
) -> TaskAnnotations | None:
    """Return a task's annotations from cache or a live fetch, updating *stats*.

    Returns ``None`` when a live fetch skipped the task (5xx).  Fresh
    results are cached before path population so shared S3 entries stay
    machine-independent.
    """
    started = deps.clock()
    cached = policy.read(task)
    if cached is not None:
        stats.record_hit(deps.clock() - started)
        return cached

    fetched = client.fetch_one_task(client.api, task, ctx)
    if fetched is None:
        return None
    policy.write(task, fetched)
    stats.record_fetch(deps.clock() - started)
    return fetched


def _fetch_and_save_tasks(  # noqa: PLR0913
    client: CvatClient,
    ctx: FetchContext,
    output_dir: Path,
    policy: _CachePolicy,
    *,
    deps: FetchDependencies,
    save_tasks: bool,
) -> ProjectAnnotations:
    """Fetch tasks in parallel, saving per-task CSVs into ``output_dir/.tasks/``.

    Up to ``deps.cvat_workers`` tasks are in flight at once; each is a handful
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

    tasks_dir = deps.files.prepare_tasks(output_dir)

    stats = _FetchStats(lock=deps.lock_factory())

    def process(task: TaskInfo) -> TaskAnnotations | None:
        """Perform the declared workflow operation."""
        result = _retrieve_task(client, task, ctx, policy, stats, deps=deps)
        if result is not None:
            deps.files.write_task_csv(task, result, tasks_dir)
        return result

    # catch=(): a failure that got this far is already past the retry budget
    # and the 5xx skip, so it aborts the fetch exactly as it did serially.
    outcomes = deps.runner(
        ctx.tasks,
        process,
        max_workers=deps.cvat_workers,
        catch=(),
        desc="Processing tasks",
        unit="task",
    )
    task_results = [r for r in outcomes if isinstance(r, TaskAnnotations)]

    if not save_tasks:
        deps.files.cleanup_tasks(tasks_dir)

    if policy.cache is not None:
        stats.log_summary()

    return TaskAnnotations.merge(task_results)

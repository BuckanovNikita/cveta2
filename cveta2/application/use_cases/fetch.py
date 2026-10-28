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
    config_path: Path | None = None


def fetch_project(
    client: CvatClient,
    target: FetchTarget,
    options: FetchOptions,
    *,
    deps: FetchDependencies,
) -> PartitionResult:
    """Full-project fetch: partition outputs and optional raw.csv.

    Writes dataset/obsolete/in_progress/deleted CSVs (plus raw.csv when
    ``options.raw``) into ``target.output_dir`` and returns the partition.
    """
    fetch_started = deps.clock()
    output_dir = target.output_dir
    if options.skip_validation:
        started = deps.clock()
        _promote_completed_annotations(client, target, options, deps=deps)
        logger.info(
            f"Принятие завершённой разметки: прошло {deps.clock() - started:.1f} с"
        )
    result = _fetch_core(client, target, options, prune_cache=True, deps=deps)

    if options.raw:
        started = deps.clock()
        deps.files.write_raw_csv(result, output_dir)
        logger.info(f"Запись raw.csv: прошло {deps.clock() - started:.1f} с")

    started = deps.clock()
    df = pd.DataFrame(result.to_csv_rows(), columns=list(CSV_COLUMNS))
    partition = partition_annotations_df(df, result.deleted_images)
    deps.files.write_partition_csvs(partition, output_dir)
    logger.info(
        f"Партиционирование и запись CSV: прошло {deps.clock() - started:.1f} с"
    )
    logger.info(f"Выгрузка завершена: прошло {deps.clock() - fetch_started:.1f} с")

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
    fetch_started = deps.clock()
    result = _fetch_core(client, target, options, prune_cache=False, deps=deps)
    started = deps.clock()
    deps.files.write_dataset_and_deleted(result, target.output_dir)
    logger.info(f"Запись CSV: прошло {deps.clock() - started:.1f} с")
    logger.info(f"Выгрузка завершена: прошло {deps.clock() - fetch_started:.1f} с")
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
    logger.info(
        f"Отбор задач: {len(ctx.tasks)} к загрузке; "
        f"прошло {deps.clock() - started:.1f} с"
    )

    started = deps.clock()
    cache_settings = deps.cache_settings
    cache = _build_task_cache(client, project_id, options, cache_settings, deps=deps)
    policy = _CachePolicy(cache=cache, force=options.force)
    logger.info(f"Подготовка кэша аннотаций: прошло {deps.clock() - started:.1f} с")

    result = _fetch_and_save_tasks(
        client,
        ctx,
        target.output_dir,
        policy,
        save_tasks=options.save_tasks,
        deps=deps,
    )

    if cache is not None and prune_cache and ctx.all_task_ids is not None:
        started = deps.clock()
        pruned = cache.prune(set(ctx.all_task_ids))
        if pruned:
            logger.info(f"Кэш аннотаций: удалено устаревших записей: {pruned}")
        logger.info(f"Очистка кэша аннотаций: прошло {deps.clock() - started:.1f} с")

    if options.images_dir is not None:
        started = deps.clock()
        stats = client.download_images(
            result,
            options.images_dir,
            project_id=project_id,
            project_cloud_storage=target.cs_info,
            ignored_prefix=cache_settings.ignored_prefix,
        )
        logger.info(
            f"Изображения: {stats.summary()}; прошло {deps.clock() - started:.1f} с"
        )
    started = deps.clock()
    deps.files.populate_record_paths(
        result,
        target.cs_info,
        options.images_dir,
        ignored_prefix=cache_settings.ignored_prefix,
    )
    logger.info(f"Пути изображений: прошло {deps.clock() - started:.1f} с")

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
    skipped_seconds: float = 0.0
    skipped_task_ids: list[int] = field(default_factory=list)
    degraded_task_ids: list[int] = field(default_factory=list)

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

    def record_skip(self, task_id: int, seconds: float) -> None:
        """Record an unsuccessful task separately from completed live fetches."""
        with self.lock:
            self.skipped_task_ids.append(task_id)
            self.skipped_seconds += seconds

    def record_degraded(self, task_id: int) -> None:
        """Record incomplete issues without double-counting the fetched task."""
        with self.lock:
            self.degraded_task_ids.append(task_id)

    def log_summary(self, elapsed: float) -> None:
        """Distinguish stage wall time from overlapping worker-duration sums."""
        logger.info(
            f"Обработка задач: прошло {elapsed:.1f} с; "
            f"из кэша: {self.cache_hits}, загружено с CVAT: {self.fetched}, "
            f"пропущено: {len(self.skipped_task_ids)}, "
            f"неполные issues: {len(self.degraded_task_ids)}. "
            f"Суммы времени работников: кэш {self.hit_seconds:.1f} с, "
            f"CVAT {self.fetch_seconds:.1f} с, пропуски {self.skipped_seconds:.1f} с "
            "(суммарное время работников, не длительность этапа)"
        )
        if self.skipped_task_ids:
            logger.warning(
                f"Пропущены задачи ({len(self.skipped_task_ids)}): "
                f"{sorted(self.skipped_task_ids)}; выгрузка неполная"
            )
        if self.degraded_task_ids:
            logger.warning(
                f"Неполные issues в задачах ({len(self.degraded_task_ids)}): "
                f"{sorted(self.degraded_task_ids)}; сведения об issues отсутствуют"
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
        if not cached.issues_complete:
            stats.record_degraded(task.id)
        return cached

    fetched = client.fetch_one_task(client.api, task, ctx)
    if fetched is None:
        stats.record_skip(task.id, deps.clock() - started)
        return None
    policy.write(task, fetched)
    stats.record_fetch(deps.clock() - started)
    if not fetched.issues_complete:
        stats.record_degraded(task.id)
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
    """Fetch tasks in parallel, optionally saving CSVs into ``output_dir/.tasks/``.

    Up to ``deps.cvat_workers`` tasks are in flight at once; each is a handful
    of CVAT round-trips that spend nearly all their time waiting.  Results are
    returned in task order regardless of completion order, so the merged
    output does not depend on which task happened to finish first.

    Completed tasks are served from *policy*'s cache when possible. Only
    *save_tasks* accesses ``.tasks/``: an ordinary fetch leaves a pre-existing
    directory untouched, including files belonging to previous runs.

    Returns the merged :class:`ProjectAnnotations` from all fetched tasks.
    """
    started = deps.clock()
    stats = _FetchStats(lock=deps.lock_factory())
    if not ctx.tasks:
        logger.warning("Нет задач для выгрузки.")
        stats.log_summary(deps.clock() - started)
        return TaskAnnotations.merge([])

    tasks_dir = deps.files.prepare_tasks(output_dir) if save_tasks else None

    def process(task: TaskInfo) -> TaskAnnotations | None:
        """Perform the declared workflow operation."""
        result = _retrieve_task(client, task, ctx, policy, stats, deps=deps)
        if result is not None and tasks_dir is not None:
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
    result = TaskAnnotations.merge(task_results)
    stats.log_summary(deps.clock() - started)
    return result

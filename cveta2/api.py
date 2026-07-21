"""Public workflow API: module-level functions mirroring the data CLI commands.

Every data command (fetch, upload, convert, merge, labels, task ops,
whats-new, ignore, s3-sync) has a counterpart here; the interactive-only
commands (``setup``, ``setup-cache``, ``setup-clearml``, ``doctor``) do not.

Every remote function accepts an optional ``connection=`` argument (a
:class:`Connection`); when omitted or partially filled, configuration is
resolved from environment variables, ``~/.config/cveta2/config.yaml``
and the built-in preset.  The API never prompts — missing settings raise
:class:`MissingHostError` / :class:`MissingCredentialsError`.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pandas as pd
from pydantic import BaseModel

from cveta2._client.connection import configure_data_timeout
from cveta2.client import CvatClient
from cveta2.config import (
    CacheConfig,
    CvatConfig,
    IgnoreConfig,
    UploadConfig,
    resolve_images_cache_dir,
)
from cveta2.exceptions import Cveta2Error, MissingHostError
from cveta2.models import JOB_STAGES, JOB_STATES, TaskInfo
from cveta2.services.convert import (
    convert_from_yolo,
    convert_to_coco,
    convert_to_yolo,
)
from cveta2.services.fetch import (
    FetchOptions,
    fetch_project,
    fetch_selected_tasks,
    load_ignore_sets,
)
from cveta2.services.merge import merge_datasets
from cveta2.services.output import read_dataset_csv
from cveta2.services.resolve import apply_sync_root_override, resolve_project_spec
from cveta2.services.upload import (
    UploadOptions,
    UploadRequest,
    build_search_dirs,
    build_upload_plan,
    read_exclude_names,
    split_deleted_rows,
    upload_dataset,
)
from cveta2.services.whats_new import REQUIRED_COLUMNS, compute_baseline
from cveta2.task_cache import invalidate_local_entry

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from cveta2.config import IgnoredTask
    from cveta2.dataset_partition import PartitionResult
    from cveta2.image_downloader import DownloadStats
    from cveta2.models import JobStage, JobState, LabelInfo

__all__ = [
    "Connection",
    "UploadResult",
    "WhatsNewResult",
    "convert_from_yolo",
    "convert_to_coco",
    "convert_to_yolo",
    "fetch",
    "fetch_task",
    "get_labels",
    "ignore",
    "merge",
    "s3_sync",
    "task_delete",
    "task_drop_label",
    "task_mark_deleted",
    "task_set_status",
    "update_labels",
    "upload",
    "whats_new",
]

CacheMode = Literal["use", "refresh", "off"]
"""Task-annotation cache modes for :func:`fetch` / :func:`fetch_task`."""

_CACHE_FLAGS: dict[str, tuple[bool, bool]] = {
    "use": (True, False),
    "refresh": (True, True),
    "off": (False, False),
}


class UploadResult(BaseModel):
    """Summary of a completed upload."""

    task_id: int
    task_name: str
    url: str
    images: int
    deleted: int
    annotations: int
    issues: int


@dataclass(frozen=True, slots=True)
class Connection:
    """Explicit CVAT connection settings for the public API.

    All fields are optional; missing values resolve from environment
    variables, the config file and the built-in preset (explicit > env >
    file > preset).  ``client`` injects a ready client (tests /
    connection reuse): it must be already entered, or constructed with a
    fake ``api=``; it is neither entered nor closed here.
    """

    host: str | None = None
    username: str | None = None
    password: str | None = None
    organization: str | None = None
    config_path: Path | None = None
    client: CvatClient | None = None


@contextmanager
def _open(connection: Connection | None) -> Iterator[CvatClient]:
    """Yield a ready CvatClient: injected as-is, or opened from config.

    Resolution order: explicit settings > env vars > config file >
    preset.  Never prompts.
    """
    conn = connection or Connection()
    if conn.client is not None:
        if not conn.client.is_ready:
            raise Cveta2Error(
                "Переданный client не готов к работе: войдите в его контекст "
                "(with CvatClient(cfg) as client: ...) или создайте его "
                "с фейковым api=."
            )
        yield conn.client
        return
    cfg = CvatConfig.load(conn.config_path)
    cfg = cfg.merge(
        CvatConfig(
            host=conn.host or "",
            username=conn.username,
            password=conn.password,
            organization=conn.organization,
        )
    )
    if not cfg.host:
        raise MissingHostError(
            "Хост CVAT не настроен. Передайте host= или задайте CVAT_HOST "
            "(либо cvat.host в конфигурации)."
        )
    configure_data_timeout(cfg.request_timeout)
    with CvatClient(cfg) as opened:
        yield opened


def _config_path(connection: Connection | None) -> Path | None:
    """Explicit config file from the connection, or None for the default."""
    return connection.config_path if connection else None


def _cache_flags(cache: CacheMode) -> tuple[bool, bool]:
    """Map a cache mode onto the ``(use_cache, force)`` fetch options."""
    try:
        return _CACHE_FLAGS[cache]
    except KeyError:
        raise Cveta2Error(
            f"Недопустимое значение cache={cache!r}; допустимые: use, refresh, off."
        ) from None


def _resolve_images_dir(
    images_dir: str | Path | None,
    download_images: bool,  # noqa: FBT001
    project_name: str,
    config_path: Path | None,
) -> Path | None:
    """Resolve the image download directory without prompting."""
    if images_dir and not download_images:
        raise Cveta2Error(
            "Параметры несовместимы: передан images_dir= при download_images=False."
        )
    if not download_images:
        return None
    if images_dir:
        return Path(images_dir).resolve()
    configured = resolve_images_cache_dir(project_name, config_path)
    if configured is not None:
        return configured
    raise Cveta2Error(
        f"Путь кэширования изображений для проекта {project_name!r} не "
        f"настроен. Передайте images_dir=, download_images=False или "
        f"добавьте image_cache.{project_name} (или cache.images_root) "
        f"в конфигурацию."
    )


def fetch(  # noqa: PLR0913
    project: int | str,
    output_dir: str | Path,
    *,
    completed_only: bool = False,
    raw: bool = False,
    images_dir: str | Path | None = None,
    download_images: bool = True,
    cache: CacheMode = "use",
    save_tasks: bool = False,
    publish_clearml: bool = True,
    connection: Connection | None = None,
) -> PartitionResult:
    """Fetch a whole project like ``cveta2 fetch``.

    Writes dataset/obsolete/in_progress/deleted CSVs (plus raw.csv when
    *raw*) into *output_dir* and returns the full
    :class:`~cveta2.dataset_partition.PartitionResult` — the
    ``dataset`` / ``obsolete`` / ``in_progress`` DataFrames plus
    ``deleted_images``.  DataFrame columns follow
    :data:`cveta2.CSV_COLUMNS`; rows are flattened
    :data:`cveta2.AnnotationRecord` variants (see ``DATASET_FORMAT.md``).

    *cache* controls the task-annotation cache: ``"use"`` reads and
    updates it, ``"refresh"`` re-downloads every task and updates it,
    ``"off"`` disables it entirely.
    """
    use_cache, force = _cache_flags(cache)
    config_path = _config_path(connection)
    with _open(connection) as c:
        project_id, project_name = resolve_project_spec(c, project)
        cs_info = apply_sync_root_override(
            project_name, c.detect_project_cloud_storage(project_id)
        )
        ignore_set, silent_set = load_ignore_sets(project_name, config_path)
        options = FetchOptions(
            completed_only=completed_only,
            ignore_task_ids=ignore_set,
            silent_task_ids=silent_set,
            use_cache=use_cache,
            force=force,
            save_tasks=save_tasks,
            images_dir=_resolve_images_dir(
                images_dir, download_images, project_name, config_path
            ),
            raw=raw,
            publish_clearml=publish_clearml,
            config_path=config_path,
        )
        return fetch_project(
            c, project_id, project_name, Path(output_dir), cs_info, options
        )


def fetch_task(  # noqa: PLR0913
    project: int | str,
    tasks: Sequence[int | str],
    output_dir: str | Path,
    *,
    completed_only: bool = False,
    images_dir: str | Path | None = None,
    download_images: bool = True,
    cache: CacheMode = "use",
    save_tasks: bool = False,
    connection: Connection | None = None,
) -> pd.DataFrame:
    """Fetch selected tasks like ``cveta2 fetch-task``.

    Writes dataset.csv and deleted.csv into *output_dir* and returns all
    fetched rows as a DataFrame with :data:`cveta2.CSV_COLUMNS` columns
    (unpartitioned, unlike :func:`fetch`).  *cache* works as in
    :func:`fetch`.
    """
    use_cache, force = _cache_flags(cache)
    config_path = _config_path(connection)
    with _open(connection) as c:
        project_id, project_name = resolve_project_spec(c, project)
        cs_info = apply_sync_root_override(
            project_name, c.detect_project_cloud_storage(project_id)
        )
        ignore_set, silent_set = load_ignore_sets(project_name, config_path)
        options = FetchOptions(
            completed_only=completed_only,
            task_selector=list(tasks),
            ignore_task_ids=ignore_set,
            silent_task_ids=silent_set,
            use_cache=use_cache,
            force=force,
            save_tasks=save_tasks,
            images_dir=_resolve_images_dir(
                images_dir, download_images, project_name, config_path
            ),
            config_path=config_path,
        )
        result = fetch_selected_tasks(
            c, project_id, project_name, Path(output_dir), cs_info, options
        )
    return pd.DataFrame(result.to_csv_rows())


def upload(  # noqa: PLR0913
    dataset: str | Path | pd.DataFrame,
    project: int | str,
    name: str,
    *,
    labels: Sequence[str] | None = None,
    include_unannotated: bool = False,
    exclude_in_progress: str | Path | None = None,
    image_dirs: Sequence[str | Path] | None = None,
    complete: bool = False,
    mark_all_deleted: bool = False,
    connection: Connection | None = None,
) -> UploadResult:
    """Upload a dataset back to CVAT like ``cveta2 upload``.

    *labels* selects frames by their annotations (co-occurring labels of
    the chosen frames are included); ``labels=None`` uploads all frames.
    Rows with ``issue_state="new"`` become CVAT issues; rows with
    ``instance_shape="deleted"`` are marked as deleted frames.
    """
    df = (
        dataset
        if isinstance(dataset, pd.DataFrame)
        else read_dataset_csv(Path(dataset), {"image_name", "instance_label"})
    )
    df_normal, deleted_names = split_deleted_rows(df)
    exclude_names = read_exclude_names(
        str(exclude_in_progress) if exclude_in_progress else None
    )
    if labels is None:
        labels = sorted(df_normal["instance_label"].dropna().unique())
        include_unannotated = True
    plan = build_upload_plan(
        df_normal,
        deleted_names,
        labels=list(labels),
        include_unannotated=include_unannotated,
        exclude_names=exclude_names,
    )
    upload_cfg = UploadConfig.load(_config_path(connection))
    with _open(connection) as c:
        project_id, project_name = resolve_project_spec(c, project)
        options = UploadOptions(
            search_dirs=build_search_dirs(image_dirs, project_name),
            segment_size=upload_cfg.images_per_job,
            image_quality=upload_cfg.image_quality,
            mark_all_deleted=mark_all_deleted,
            complete=complete,
        )
        request = UploadRequest(
            project_id=project_id,
            project_name=project_name,
            task_name=name,
            plan=plan,
            options=options,
        )
        outcome = upload_dataset(c, request)
        return UploadResult(
            task_id=outcome.task_id,
            task_name=outcome.task_name,
            url=f"{c.host}/tasks/{outcome.task_id}",
            images=outcome.images,
            deleted=outcome.deleted,
            annotations=outcome.annotations,
            issues=outcome.issues,
        )


def merge(
    old: str | Path,
    new: str | Path,
    output: str | Path,
    *,
    deleted: str | Path | None = None,
    by_time: bool = False,
) -> pd.DataFrame:
    """Merge two fetched datasets like ``cveta2 merge``."""
    return merge_datasets(old, new, output, deleted=deleted, by_time=by_time)


class WhatsNewResult(BaseModel):
    """Completed tasks newer than a fetched dataset CSV."""

    tasks: list[TaskInfo]
    updated_task_ids: set[int]
    cutoff: str


def whats_new(
    project: int | str,
    dataset: str | Path,
    *,
    connection: Connection | None = None,
) -> WhatsNewResult:
    """List completed tasks newer than a fetched dataset CSV.

    ``updated_task_ids`` marks the returned tasks that are already
    present in the CSV (updated since the fetch, rather than new).
    """
    dataset_path = Path(dataset)
    df = read_dataset_csv(dataset_path, REQUIRED_COLUMNS)
    baseline = compute_baseline(df, dataset_path)
    with _open(connection) as c:
        project_id, _ = resolve_project_spec(c, project)
        tasks = c.list_tasks_completed_after(project_id, baseline.cutoff)
    return WhatsNewResult(
        tasks=tasks,
        updated_task_ids={t.id for t in tasks if t.id in baseline.known_task_ids},
        cutoff=baseline.cutoff,
    )


def s3_sync(
    project: int | str,
    target_dir: str | Path,
    *,
    root: str | None = None,
    connection: Connection | None = None,
) -> DownloadStats:
    """Sync all project images from S3 into *target_dir* like ``cveta2 s3-sync``."""
    config_path = _config_path(connection)
    with _open(connection) as c:
        project_id, project_name = resolve_project_spec(c, project)
        cs_info = apply_sync_root_override(
            project_name, c.detect_project_cloud_storage(project_id), root
        )
        ignored_prefix = (
            CacheConfig.load(config_path).for_project(project_name).ignored_prefix
        )
        return c.sync_project_images(
            project_id, Path(target_dir), cs_info, ignored_prefix=ignored_prefix
        )


def get_labels(
    project: int | str,
    *,
    connection: Connection | None = None,
) -> list[LabelInfo]:
    """Return the project's label definitions."""
    with _open(connection) as c:
        project_id, _ = resolve_project_spec(c, project)
        return c.get_project_labels(project_id)


def update_labels(  # noqa: PLR0913
    project: int | str,
    *,
    add: list[str] | None = None,
    rename: dict[int, str] | None = None,
    delete: list[int] | None = None,
    recolor: dict[int, str] | None = None,
    connection: Connection | None = None,
) -> None:
    """Add/rename/delete/recolor project labels.

    *add* takes new label names; *delete* takes label IDs (from
    :func:`get_labels`).  *rename* maps label ID → new name and *recolor*
    maps label ID → hex color (``"#rrggbb"``).  Deleting labels destroys
    all annotations using them permanently.
    """
    with _open(connection) as c:
        project_id, _ = resolve_project_spec(c, project)
        c.update_project_labels(
            project_id, add=add, rename=rename, delete=delete, recolor=recolor
        )


def ignore(  # noqa: PLR0913
    project: int | str,
    *,
    add: Sequence[int | str] | None = None,
    remove: Sequence[int | str] | None = None,
    description: str = "",
    silent: bool = False,
    connection: Connection | None = None,
) -> list[IgnoredTask]:
    """Manage the project's fetch ignore list like ``cveta2 ignore``.

    *add* / *remove* take task IDs or names; *description* and *silent*
    apply to added tasks.  Returns the project's ignore entries after the
    change (with neither *add* nor *remove*, just lists them).
    """
    config_path = _config_path(connection)
    ignore_cfg = IgnoreConfig.load(config_path)
    with _open(connection) as c:
        project_id, project_name = resolve_project_spec(c, project)
        if add or remove:
            tasks = c.list_project_tasks(project_id)
            for task in c.resolve_task_selectors(tasks, list(add or [])):
                ignore_cfg.add_task(
                    project_name, task.id, task.name, description, silent=silent
                )
            for task in c.resolve_task_selectors(tasks, list(remove or [])):
                ignore_cfg.remove_task(project_name, task.id)
            ignore_cfg.save(config_path)
    return ignore_cfg.get_ignored_entries(project_name)


def _resolve_task(client: CvatClient, project_id: int, task: int | str) -> TaskInfo:
    tasks = client.list_project_tasks(project_id)
    return client.resolve_task_selectors(tasks, [task])[0]


@contextmanager
def _resolved_task(
    connection: Connection | None,
    project: int | str,
    task: int | str,
) -> Iterator[tuple[CvatClient, TaskInfo]]:
    """Open a client, resolve *project*/*task*, and invalidate the cache on exit.

    Every task mutation shares this scaffold; centralising the local
    cache-invalidation here keeps a stale entry from surviving a future
    mutation that forgets to call ``invalidate_local_entry``.
    """
    with _open(connection) as c:
        project_id, project_name = resolve_project_spec(c, project)
        task_info = _resolve_task(c, project_id, task)
        try:
            yield c, task_info
        finally:
            invalidate_local_entry(project_id, task_info.id, project_name)


def task_mark_deleted(
    project: int | str,
    task: int | str,
    *,
    frames: Iterable[int] | None = None,
    images: Iterable[str] | None = None,
    connection: Connection | None = None,
) -> int:
    """Mark frames of a task as deleted (by frame ids and/or image names)."""
    if not frames and not images:
        raise Cveta2Error("Укажите хотя бы один frame или image.")
    with _resolved_task(connection, project, task) as (c, task_info):
        marked = 0
        if images:
            marked += c.mark_frames_deleted(task_info.id, set(images))
        if frames:
            marked += c.mark_frames_deleted_by_ids(task_info.id, frames)
        return marked


def task_drop_label(
    project: int | str,
    task: int | str,
    label: str,
    *,
    connection: Connection | None = None,
) -> int:
    """Delete all annotation shapes with *label* from a task."""
    with _resolved_task(connection, project, task) as (c, task_info):
        return c.drop_label_annotations(task_info.id, label)


def task_delete(
    project: int | str,
    task: int | str,
    *,
    connection: Connection | None = None,
) -> None:
    """Delete a CVAT task permanently."""
    with _resolved_task(connection, project, task) as (c, task_info):
        c.delete_task(task_info.id)


def task_set_status(
    project: int | str,
    task: int | str,
    *,
    stage: JobStage | None = None,
    state: JobState | None = None,
    connection: Connection | None = None,
) -> int:
    """Set stage and/or state on every job of a task (CVAT-native values).

    Valid values: :data:`cveta2.JOB_STAGES` / :data:`cveta2.JOB_STATES`.
    """
    if stage is None and state is None:
        raise Cveta2Error("Укажите хотя бы один stage или state.")
    if stage is not None and stage not in JOB_STAGES:
        raise Cveta2Error(
            f"Недопустимый stage {stage!r}; допустимые: {', '.join(JOB_STAGES)}."
        )
    if state is not None and state not in JOB_STATES:
        raise Cveta2Error(
            f"Недопустимый state {state!r}; допустимые: {', '.join(JOB_STATES)}."
        )
    with _resolved_task(connection, project, task) as (c, task_info):
        return c.set_task_jobs_status(task_info.id, stage=stage, state=state)

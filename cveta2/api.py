"""Public workflow API: module-level functions mirroring the CLI commands.

Every remote function accepts optional connection kwargs
(``host``/``username``/``password``/``organization``/``config_path``);
when omitted, configuration is resolved from environment variables,
``~/.config/cveta2/config.yaml`` and the built-in preset.  The API never
prompts — missing settings raise :class:`MissingHostError` /
:class:`MissingCredentialsError`.  An injected ``client`` must be ready
to use (already entered, or constructed with a fake ``api=``); it is
neither entered nor closed here.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from pydantic import BaseModel

from cveta2._client.connection import configure_data_timeout
from cveta2.client import CvatClient
from cveta2.config import (
    CvatConfig,
    load_image_cache_config,
    load_upload_config,
)
from cveta2.exceptions import Cveta2Error, MissingHostError
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
from cveta2.services.resolve import apply_sync_root_override, resolve_project
from cveta2.services.upload import (
    UploadOptions,
    build_search_dirs,
    build_upload_plan,
    read_exclude_names,
    split_deleted_rows,
    upload_dataset,
)
from cveta2.services.whats_new import REQUIRED_COLUMNS, compute_cutoff
from cveta2.task_cache import invalidate_local_entry

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from cveta2.image_downloader import DownloadStats
    from cveta2.models import LabelInfo, TaskInfo

__all__ = [
    "UploadResult",
    "convert_from_yolo",
    "convert_to_coco",
    "convert_to_yolo",
    "fetch",
    "fetch_task",
    "get_labels",
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


class UploadResult(BaseModel):
    """Summary of a completed upload."""

    task_id: int
    task_name: str
    url: str
    images: int
    deleted: int
    annotations: int
    issues: int


class _ConnectionSettings(BaseModel):
    """Bundle of optional connection overrides shared by every API function."""

    host: str | None = None
    username: str | None = None
    password: str | None = None
    organization: str | None = None
    config_path: Path | None = None


def _conn(
    host: str | None,
    username: str | None,
    password: str | None,
    organization: str | None,
    config_path: Path | None,
) -> _ConnectionSettings:
    """Build a ``_ConnectionSettings`` from the shared per-function kwargs."""
    return _ConnectionSettings(
        host=host,
        username=username,
        password=password,
        organization=organization,
        config_path=config_path,
    )


@contextmanager
def _resolve_client(
    client: CvatClient | None,
    conn: _ConnectionSettings,
) -> Iterator[CvatClient]:
    """Yield a ready CvatClient: injected as-is, or opened from config.

    Resolution order: explicit kwargs > env vars > config file > preset.
    Never prompts.
    """
    if client is not None:
        yield client
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


def _resolve_images_dir(
    images_dir: str | Path | None,
    download_images: bool,  # noqa: FBT001
    project_name: str,
) -> Path | None:
    """Resolve the image download directory without prompting."""
    if not download_images:
        return None
    if images_dir:
        return Path(images_dir).resolve()
    cached_dir = load_image_cache_config().get_cache_dir(project_name)
    if cached_dir is not None:
        return cached_dir
    raise Cveta2Error(
        f"Путь кэширования изображений для проекта {project_name!r} не "
        f"настроен. Передайте images_dir=, download_images=False или "
        f"добавьте image_cache.{project_name} в конфигурацию."
    )


def fetch(  # noqa: PLR0913
    project: int | str,
    output_dir: str | Path,
    *,
    completed_only: bool = False,
    raw: bool = False,
    images_dir: str | Path | None = None,
    download_images: bool = True,
    use_cache: bool = True,
    force: bool = False,
    save_tasks: bool = False,
    publish_clearml: bool = True,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> pd.DataFrame:
    """Fetch a whole project like ``cveta2 fetch``.

    Writes dataset/obsolete/in_progress/deleted CSVs (plus raw.csv when
    *raw*) into *output_dir* and returns the ``dataset`` partition.
    """
    with _resolve_client(
        client, _conn(host, username, password, organization, config_path)
    ) as c:
        project_id, project_name = resolve_project(c, project)
        cs_info = apply_sync_root_override(
            project_name, c.detect_project_cloud_storage(project_id)
        )
        ignore_set, silent_set = load_ignore_sets(project_name)
        options = FetchOptions(
            completed_only=completed_only,
            ignore_task_ids=ignore_set,
            silent_task_ids=silent_set,
            use_cache=use_cache,
            force=force,
            save_tasks=save_tasks,
            images_dir=_resolve_images_dir(images_dir, download_images, project_name),
            raw=raw,
            publish_clearml=publish_clearml,
        )
        partition = fetch_project(
            c, project_id, project_name, Path(output_dir), cs_info, options
        )
    return partition.dataset


def fetch_task(  # noqa: PLR0913
    project: int | str,
    tasks: Sequence[int | str],
    output_dir: str | Path,
    *,
    completed_only: bool = False,
    images_dir: str | Path | None = None,
    download_images: bool = True,
    use_cache: bool = True,
    force: bool = False,
    save_tasks: bool = False,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> pd.DataFrame:
    """Fetch selected tasks like ``cveta2 fetch-task``.

    Writes dataset.csv and deleted.csv into *output_dir* and returns the
    dataset rows as a DataFrame.
    """
    with _resolve_client(
        client, _conn(host, username, password, organization, config_path)
    ) as c:
        project_id, project_name = resolve_project(c, project)
        cs_info = apply_sync_root_override(
            project_name, c.detect_project_cloud_storage(project_id)
        )
        ignore_set, silent_set = load_ignore_sets(project_name)
        options = FetchOptions(
            completed_only=completed_only,
            task_selector=list(tasks),
            ignore_task_ids=ignore_set,
            silent_task_ids=silent_set,
            use_cache=use_cache,
            force=force,
            save_tasks=save_tasks,
            images_dir=_resolve_images_dir(images_dir, download_images, project_name),
        )
        result = fetch_selected_tasks(
            c, project_id, project_name, Path(output_dir), cs_info, options
        )
    return pd.DataFrame(result.to_csv_rows())


def upload(  # noqa: PLR0913
    dataset: str | Path | pd.DataFrame,
    *,
    project: int | str,
    name: str,
    labels: Sequence[str] | None = None,
    include_unannotated: bool = False,
    exclude_in_progress: str | Path | None = None,
    image_dirs: Sequence[str | Path] | None = None,
    complete: bool = False,
    mark_all_deleted: bool = False,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
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
    upload_cfg = load_upload_config()
    with _resolve_client(
        client, _conn(host, username, password, organization, config_path)
    ) as c:
        project_id, project_name = resolve_project(c, project)
        options = UploadOptions(
            search_dirs=build_search_dirs(image_dirs, project_name),
            segment_size=upload_cfg.images_per_job,
            image_quality=upload_cfg.image_quality,
            mark_all_deleted=mark_all_deleted,
            complete=complete,
        )
        outcome = upload_dataset(c, project_id, project_name, plan, name, options)
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


def whats_new(  # noqa: PLR0913
    project: int | str,
    dataset: str | Path,
    *,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> list[TaskInfo]:
    """List completed tasks newer than a fetched dataset CSV."""
    dataset_path = Path(dataset)
    df = read_dataset_csv(dataset_path, REQUIRED_COLUMNS)
    cutoff = compute_cutoff(df, dataset_path)
    with _resolve_client(
        client, _conn(host, username, password, organization, config_path)
    ) as c:
        project_id, _ = resolve_project(c, project)
        return c.list_tasks_completed_after(project_id, cutoff)


def s3_sync(  # noqa: PLR0913
    project: int | str,
    target_dir: str | Path,
    *,
    root: str | None = None,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> DownloadStats:
    """Sync all project images from S3 into *target_dir* like ``cveta2 s3-sync``."""
    with _resolve_client(
        client, _conn(host, username, password, organization, config_path)
    ) as c:
        project_id, project_name = resolve_project(c, project)
        cs_info = apply_sync_root_override(
            project_name, c.detect_project_cloud_storage(project_id), root
        )
        return c.sync_project_images(project_id, Path(target_dir), cs_info)


def get_labels(  # noqa: PLR0913
    project: int | str,
    *,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> list[LabelInfo]:
    """Return the project's label definitions."""
    with _resolve_client(
        client, _conn(host, username, password, organization, config_path)
    ) as c:
        project_id, _ = resolve_project(c, project)
        return c.get_project_labels(project_id)


def update_labels(  # noqa: PLR0913
    project: int | str,
    *,
    add: list[str] | None = None,
    rename: dict[int, str] | None = None,
    delete: list[int] | None = None,
    recolor: dict[int, str] | None = None,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> None:
    """Add/rename/delete/recolor project labels.

    Deleting labels destroys all annotations using them permanently.
    """
    with _resolve_client(
        client, _conn(host, username, password, organization, config_path)
    ) as c:
        project_id, _ = resolve_project(c, project)
        c.update_project_labels(
            project_id, add=add, rename=rename, delete=delete, recolor=recolor
        )


def _resolve_task(client: CvatClient, project_id: int, task: int | str) -> TaskInfo:
    """Resolve a task selector within a project."""
    tasks = client.list_project_tasks(project_id)
    return client.resolve_task_selectors(tasks, [task])[0]


@contextmanager
def _resolved_task(
    client: CvatClient | None,
    conn: _ConnectionSettings,
    project: int | str,
    task: int | str,
) -> Iterator[tuple[CvatClient, TaskInfo]]:
    """Open a client, resolve *project*/*task*, and invalidate the cache on exit.

    Every task mutation shares this scaffold; centralising the local
    cache-invalidation here keeps a stale entry from surviving a future
    mutation that forgets to call ``invalidate_local_entry``.
    """
    with _resolve_client(client, conn) as c:
        project_id, _ = resolve_project(c, project)
        task_info = _resolve_task(c, project_id, task)
        try:
            yield c, task_info
        finally:
            invalidate_local_entry(project_id, task_info.id)


def task_mark_deleted(  # noqa: PLR0913
    project: int | str,
    task: int | str,
    *,
    frames: Iterable[int] | None = None,
    images: Iterable[str] | None = None,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> int:
    """Mark frames of a task as deleted (by frame ids and/or image names)."""
    if not frames and not images:
        raise Cveta2Error("Укажите хотя бы один frame или image.")
    conn = _conn(host, username, password, organization, config_path)
    with _resolved_task(client, conn, project, task) as (c, task_info):
        marked = 0
        if images:
            marked += c.mark_frames_deleted(task_info.id, set(images))
        if frames:
            marked += c.mark_frames_deleted_by_ids(task_info.id, frames)
        return marked


def task_drop_label(  # noqa: PLR0913
    project: int | str,
    task: int | str,
    label: str,
    *,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> int:
    """Delete all annotation shapes with *label* from a task."""
    conn = _conn(host, username, password, organization, config_path)
    with _resolved_task(client, conn, project, task) as (c, task_info):
        return c.drop_label_annotations(task_info.id, label)


def task_delete(  # noqa: PLR0913
    project: int | str,
    task: int | str,
    *,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> None:
    """Delete a CVAT task permanently."""
    conn = _conn(host, username, password, organization, config_path)
    with _resolved_task(client, conn, project, task) as (c, task_info):
        c.delete_task(task_info.id)


def task_set_status(  # noqa: PLR0913
    project: int | str,
    task: int | str,
    *,
    stage: str | None = None,
    state: str | None = None,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    organization: str | None = None,
    config_path: Path | None = None,
    client: CvatClient | None = None,
) -> int:
    """Set stage and/or state on every job of a task (CVAT-native values)."""
    conn = _conn(host, username, password, organization, config_path)
    with _resolved_task(client, conn, project, task) as (c, task_info):
        return c.set_task_jobs_status(task_info.id, stage=stage, state=state)

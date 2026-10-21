"""Public dataset merge and project labels, ignores, sync and baseline APIs."""

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd  # noqa: TC002 - Preserve runtime resolution of merge's return annotation.

from cveta2.application.use_cases.resolve import resolve_project_spec
from cveta2.composition.configuration import CacheConfig, IgnoreConfig
from cveta2.composition.conversion import compute_baseline, merge_datasets
from cveta2.composition.files import read_dataset_csv
from cveta2.composition.workflows import project_cloud_storage
from cveta2.domain.baseline import REQUIRED_COLUMNS
from cveta2.interfaces.api.connection import _config_path, _open
from cveta2.interfaces.api.types import Connection, WhatsNewResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cveta2.composition.configuration import IgnoredTask
    from cveta2.domain.models import LabelInfo
    from cveta2.domain.storage import DownloadStats


def merge(
    old: str | Path,
    new: str | Path,
    output: str | Path,
    *,
    deleted: str | Path | None = None,
    by_task: bool = False,
) -> "pd.DataFrame":
    """Merge two fetched datasets like ``cveta2 merge``."""
    return merge_datasets(old, new, output, deleted=deleted, by_task=by_task)


def whats_new(
    project: int | str,
    dataset: str | Path,
    *,
    connection: "Connection | None" = None,
) -> "WhatsNewResult":
    """List completed tasks a fetched dataset CSV does not account for.

    ``cutoff`` is the highest ``task_id`` the CSV holds for a completed
    task, for reference. A completed task is returned when it was not already
    recorded as completed in the dataset and its obsolete/deleted sibling
    CSVs, including tasks that were still in progress and have since finished.
    """
    dataset_path = Path(dataset)
    df = read_dataset_csv(dataset_path, REQUIRED_COLUMNS)
    baseline = compute_baseline(df, dataset_path)
    with _open(connection) as c:
        project_id, _ = resolve_project_spec(c, project)
        tasks = c.list_new_completed_tasks(
            project_id, baseline.cutoff, baseline.known_task_ids
        )
    return WhatsNewResult(tasks=tasks, cutoff=baseline.cutoff)


def s3_sync(
    project: int | str,
    target_dir: str | Path,
    *,
    root: str | None = None,
    connection: "Connection | None" = None,
) -> "DownloadStats":
    """Sync all project images from S3 into *target_dir* like ``cveta2 s3-sync``."""
    config_path = _config_path(connection)
    with _open(connection) as c:
        project_id, project_name = resolve_project_spec(c, project)
        cs_info = project_cloud_storage(
            c, project_id, project_name, root, config_path=config_path
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
    connection: "Connection | None" = None,
) -> "list[LabelInfo]":
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
    connection: "Connection | None" = None,
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
    add: "Sequence[int | str] | None" = None,
    remove: "Sequence[int | str] | None" = None,
    description: str = "",
    silent: bool = False,
    connection: "Connection | None" = None,
) -> "list[IgnoredTask]":
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
            stored_ids = set(ignore_cfg.get_ignored_tasks(project_name))
            local_removals = {
                int(selector)
                for selector in remove or []
                if str(selector).isdigit() and int(selector) in stored_ids
            }
            remote_removals = [
                selector
                for selector in remove or []
                if not (str(selector).isdigit() and int(selector) in local_removals)
            ]
            tasks = c.list_project_tasks(project_id) if add or remote_removals else []
            for task in c.resolve_task_selectors(tasks, list(add or [])):
                ignore_cfg.add_task(
                    project_name, task.id, task.name, description, silent=silent
                )
            resolved_removals = c.resolve_task_selectors(tasks, remote_removals)
            for task_id in local_removals:
                ignore_cfg.remove_task(project_name, task_id)
            for task in resolved_removals:
                ignore_cfg.remove_task(project_name, task.id)
            ignore_cfg.save(config_path)
    return ignore_cfg.get_ignored_entries(project_name)

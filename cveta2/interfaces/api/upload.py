"""Public CVAT upload inputs, recovery options and result mapping."""

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from cveta2.application.use_cases.resolve import resolve_project_spec
from cveta2.application.use_cases.upload import (
    UPLOAD_REQUIRED_COLUMNS,
    UploadOptions,
    UploadRequest,
    build_upload_plan,
    split_deleted_rows,
)
from cveta2.composition.configuration import UploadConfig
from cveta2.composition.files import read_dataset_csv
from cveta2.composition.workflows import (
    build_search_dirs,
    read_exclude_names,
    upload_cvat_dataset,
)
from cveta2.interfaces.api.connection import _config_path, _open
from cveta2.interfaces.api.types import Connection, UploadResult

if TYPE_CHECKING:
    from collections.abc import Sequence


def upload(  # noqa: PLR0913
    dataset: "str | Path | pd.DataFrame",
    project: int | str,
    name: str,
    *,
    labels: "Sequence[str] | None" = None,
    include_unannotated: bool = False,
    exclude_in_progress: str | Path | None = None,
    image_dirs: "Sequence[str | Path] | None" = None,
    complete: bool = False,
    mark_all_deleted: bool = False,
    resume: bool = False,
    connection: "Connection | None" = None,
) -> "UploadResult":
    """Upload a dataset back to CVAT like ``cveta2 upload``.

    *labels* selects frames by their annotations (co-occurring labels of
    the chosen frames are included); ``labels=None`` uploads all frames.
    Rows with ``issue_state="new"`` become CVAT issues; rows with
    ``instance_shape="deleted"`` are marked as deleted frames.

    *resume* continues the last unfinished upload of the same frames and
    labels instead of creating a second task, reading back from CVAT what
    the interrupted run had already managed to store.
    """
    df = (
        dataset
        if isinstance(dataset, pd.DataFrame)
        else read_dataset_csv(Path(dataset), UPLOAD_REQUIRED_COLUMNS)
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
    config_path = _config_path(connection)
    upload_cfg = UploadConfig.load(config_path)
    with _open(connection) as c:
        project_id, project_name = resolve_project_spec(c, project)
        options = UploadOptions(
            search_dirs=build_search_dirs(
                image_dirs, project_name, config_path=config_path
            ),
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
            dataset_path="" if isinstance(dataset, pd.DataFrame) else str(dataset),
            labels=tuple(labels),
            resume=resume,
        )
        outcome = upload_cvat_dataset(c, request)
        return UploadResult(
            task_id=outcome.task_id,
            task_name=outcome.task_name,
            url=f"{c.host}/tasks/{outcome.task_id}",
            images=outcome.images,
            deleted=outcome.deleted,
            annotations=outcome.annotations,
            issues=outcome.issues,
        )

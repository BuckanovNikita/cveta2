"""Prepare ordered upload rows and compute their recovery identity."""

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
from loguru import logger

from cveta2.application.ports.workflow_files import UploadFiles
from cveta2.application.use_cases.upload.types import UploadPlan, UploadRequest
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.upload import compute_fingerprint

_NOTHING_TO_UPLOAD = "Ошибка: после фильтрации не осталось изображений."


def read_exclude_names(in_progress_path: str | None, *, files: UploadFiles) -> set[str]:
    """Read excluded frame names using the supplied dataset filesystem."""
    return files.read_exclude_names(in_progress_path)


def split_deleted_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Split rows with ``instance_shape="deleted"`` out of the dataset.

    Returns ``(df_without_deleted, deleted_image_names)`` with names in
    CSV row order (deduped by first occurrence).
    """
    if "instance_shape" not in df.columns:
        return df, []
    deleted_mask = df["instance_shape"] == "deleted"
    names: list[str] = list(df.loc[deleted_mask, "image_name"].dropna().unique())
    if names:
        logger.info(
            f"Найдено удалённых изображений: {len(names)} "
            f"({int(deleted_mask.sum())} строк)"
        )
    df_normal: pd.DataFrame = df[~deleted_mask]
    return df_normal, names


def filter_frames_by_labels(
    df_normal: pd.DataFrame,
    labels: Sequence[str],
    *,
    include_unannotated: bool = False,
    exclude_names: set[str] | None = None,
) -> pd.DataFrame:
    """Return all rows of frames that contain at least one selected label.

    Selected labels choose frames (images): every annotation row of a
    chosen frame is kept, including rows whose label was not selected.
    ``include_unannotated`` selects frames with NaN labels.  Frames in
    *exclude_names* are dropped entirely.
    """
    mask = df_normal["instance_label"].isin(list(labels))
    if include_unannotated:
        mask = mask | df_normal["instance_label"].isna()
    frame_names = set(df_normal.loc[mask, "image_name"].dropna().unique())
    frame_names -= exclude_names or set()
    result: pd.DataFrame = df_normal[df_normal["image_name"].isin(frame_names)]
    return result


def build_upload_plan(
    df_normal: pd.DataFrame,
    deleted_names: list[str],
    *,
    labels: Sequence[str],
    include_unannotated: bool = False,
    exclude_names: set[str] | None = None,
) -> UploadPlan:
    """Filter frames by labels and assemble the upload plan.

    Raises :class:`Cveta2Error` when nothing remains to upload.
    """
    filtered = filter_frames_by_labels(
        df_normal,
        labels,
        include_unannotated=include_unannotated,
        exclude_names=exclude_names,
    )
    image_names: list[str] = list(filtered["image_name"].dropna().unique())
    deleted_names = [
        name for name in deleted_names if name not in (exclude_names or set())
    ]
    if not image_names and not deleted_names:
        raise Cveta2Error(_NOTHING_TO_UPLOAD)
    logger.info(
        f"Изображений для загрузки: {len(image_names)} "
        f"({len(filtered)} строк аннотаций)"
    )
    return UploadPlan(
        annotations=filtered,
        image_names=image_names,
        deleted_names=deleted_names,
    )


def build_search_dirs(
    image_dirs: Sequence[str | Path] | str | Path | None,
    project_name: str,
    *,
    cache_dir: Path | None,
) -> list[Path]:
    """Assemble already resolved local search roots in precedence order."""
    if isinstance(image_dirs, (str, Path)):
        image_dirs = [image_dirs]
    dirs = [Path(d) for d in (image_dirs or [])]
    if cache_dir is not None:
        dirs.append(cache_dir)
    if not dirs:
        logger.warning(
            "Не указан --image-dir и не настроены ни image_cache, "
            f"ни cache.images_root для проекта {project_name!r}. "
            "Будут загружены только изображения, уже находящиеся на S3.",
        )
    return dirs


def request_fingerprint(request: UploadRequest) -> str:
    """Identify all behavior-affecting intent before touching external storage."""
    return compute_fingerprint(
        request.plan.image_names,
        request.plan.deleted_names,
        request.labels,
        annotations=request.plan.annotations,
        task_name=request.task_name,
        options={
            "segment_size": request.options.segment_size,
            "image_quality": request.options.image_quality,
            "mark_all_deleted": request.options.mark_all_deleted,
            "complete": request.options.complete,
        },
    )

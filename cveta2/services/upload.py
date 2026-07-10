"""Upload pipeline orchestration: filtering, S3 upload, task creation chain.

Pure orchestration over :class:`CvatClient` — no prompts, no ``sys.exit``.
The CLI layer resolves interactive inputs (label selection, task name)
before calling in; the public API calls in directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2.config import ImageCacheConfig
from cveta2.exceptions import Cveta2Error, LabelsMismatchError
from cveta2.image_uploader import S3Uploader, build_server_file_mapping, resolve_images
from cveta2.s3_utils import build_s3_key
from cveta2.services.output import enrich_dataframe_paths
from cveta2.task_cache import invalidate_local_entry

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cveta2.client import CvatClient
    from cveta2.image_downloader import CloudStorageInfo


@dataclass(frozen=True)
class UploadPlan:
    """Resolved upload inputs: filtered rows and image-name sets."""

    annotations: pd.DataFrame
    image_names: set[str]
    deleted_names: set[str]


@dataclass(frozen=True)
class UploadOptions:
    """Options for the upload pipeline (all inputs already resolved)."""

    search_dirs: list[Path] = field(default_factory=list)
    segment_size: int = 100
    image_quality: int = 100
    mark_all_deleted: bool = False
    complete: bool = False


@dataclass(frozen=True)
class UploadRequest:
    """Fully-resolved inputs for one upload run."""

    project_id: int
    project_name: str
    task_name: str
    plan: UploadPlan
    options: UploadOptions


@dataclass(frozen=True)
class _StagedUpload:
    """Result of the S3 staging step: storage info and enriched rows."""

    cs_info: CloudStorageInfo
    annotations: pd.DataFrame
    task_image_names: list[str]


@dataclass(frozen=True)
class UploadOutcome:
    """Summary of a completed upload."""

    task_id: int
    task_name: str
    images: int
    deleted: int
    annotations: int
    issues: int
    jobs: int


def read_exclude_names(in_progress_path: str | None) -> set[str]:
    """Read in_progress.csv and return image names to exclude."""
    if not in_progress_path:
        return set()
    ip_path = Path(in_progress_path)
    if not ip_path.is_file():
        raise Cveta2Error(f"Ошибка: файл не найден: {ip_path}")
    ip_df = pd.read_csv(ip_path, encoding="utf-8")
    if "image_name" not in ip_df.columns:
        return set()
    names: set[str] = set(ip_df["image_name"].dropna().unique())
    logger.info(
        f"Исключено {len(names)} изображений ({len(ip_df)} строк) из in_progress.csv"
    )
    return names


def split_deleted_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, set[str]]:
    """Split rows with ``instance_shape="deleted"`` out of the dataset.

    Returns ``(df_without_deleted, deleted_image_names)``.
    """
    if "instance_shape" not in df.columns:
        return df, set()
    deleted_mask = df["instance_shape"] == "deleted"
    names: set[str] = set(df.loc[deleted_mask, "image_name"].dropna().unique())
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
    deleted_names: set[str],
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
    image_names = set(filtered["image_name"].dropna().unique())
    if not image_names and not deleted_names:
        raise Cveta2Error("Ошибка: после фильтрации не осталось изображений.")
    logger.info(
        f"Изображений для загрузки: {len(image_names)} "
        f"({len(filtered)} строк аннотаций)"
    )
    return UploadPlan(
        annotations=filtered,
        image_names=image_names,
        deleted_names=deleted_names,
    )


def validate_labels(
    client: CvatClient,
    project_id: int,
    project_name: str,
    labels: Sequence[str],
) -> None:
    """Check that all labels of the frames being uploaded exist in CVAT."""
    if not labels:
        return
    project_labels = client.get_project_labels(project_id)
    project_label_names = {lbl.name for lbl in project_labels}
    unknown_labels = sorted(set(labels) - project_label_names)
    if unknown_labels:
        raise LabelsMismatchError(
            unknown_labels=unknown_labels,
            project_name=project_name,
            available_labels=sorted(project_label_names),
        )


def build_search_dirs(
    image_dirs: Sequence[str | Path] | str | Path | None,
    project_name: str,
) -> list[Path]:
    """Build list of directories to search for image files."""
    if isinstance(image_dirs, (str, Path)):
        image_dirs = [image_dirs]
    dirs: list[Path] = [Path(d).resolve() for d in (image_dirs or [])]
    ic_cfg = ImageCacheConfig.load()
    cache_dir = ic_cfg.get_cache_dir(project_name)
    if cache_dir is not None:
        dirs.append(cache_dir)
    if not dirs:
        logger.warning(
            "Не указан --image-dir и не настроен image_cache "
            f"для проекта {project_name!r}. "
            "Будут загружены только изображения, "
            "уже находящиеся на S3.",
        )
    return dirs


def _warn_missing_images(missing: list[str]) -> None:
    """Log a warning about images not found locally."""
    if not missing:
        return
    preview = ", ".join(missing[:10])
    extra = f" (и ещё {len(missing) - 10})" if len(missing) > 10 else ""
    logger.warning(
        f"{len(missing)} изображений не найдено локально: {preview}{extra}",
    )


def _stage_images(client: CvatClient, request: UploadRequest) -> _StagedUpload:
    """Validate labels, upload local images to S3, enrich annotation rows."""
    plan = request.plan
    upload_labels = sorted(plan.annotations["instance_label"].dropna().unique())
    validate_labels(client, request.project_id, request.project_name, upload_labels)

    all_image_names = plan.image_names | plan.deleted_names

    found_images, missing = resolve_images(all_image_names, request.options.search_dirs)
    logger.info(
        f"Найдено локально: {len(found_images)}, не найдено: {len(missing)}",
    )

    cs_info = client.detect_project_cloud_storage(request.project_id)
    if cs_info is None:
        raise Cveta2Error(
            f"Ошибка: cloud storage не найден для проекта "
            f"{request.project_name!r} (id={request.project_id})."
        )
    logger.info(
        f"Cloud storage: s3://{cs_info.bucket}/{cs_info.prefix} (id={cs_info.id})",
    )

    name_to_server_file, existing_keys = build_server_file_mapping(
        cs_info,
        all_image_names,
    )

    annotations = enrich_dataframe_paths(
        plan.annotations, cs_info, found_images, name_to_server_file
    )

    if found_images:
        stats = S3Uploader().upload(
            cs_info,
            found_images,
            name_to_server_file,
            existing_keys,
        )
        logger.info(
            f"S3: {stats.uploaded} загружено, "
            f"{stats.skipped_existing} уже на S3, "
            f"{stats.failed} ошибок",
        )

    _warn_missing_images(missing)

    task_image_names = sorted(
        build_s3_key(cs_info.prefix, name_to_server_file[n]) for n in all_image_names
    )
    return _StagedUpload(
        cs_info=cs_info,
        annotations=annotations,
        task_image_names=task_image_names,
    )


def _push_to_cvat(
    client: CvatClient,
    request: UploadRequest,
    staged: _StagedUpload,
) -> tuple[int, int, int]:
    """Create the task and push annotations, issues and deleted frames.

    Returns ``(task_id, num_shapes, num_issues)``.
    """
    plan, options = request.plan, request.options
    task_id = client.create_upload_task(
        project_id=request.project_id,
        name=request.task_name,
        image_names=staged.task_image_names,
        cloud_storage_id=staged.cs_info.id,
        segment_size=options.segment_size,
        image_quality=options.image_quality,
    )
    session = client.open_task_session(task_id)

    num_shapes = client.upload_task_annotations(
        task_id,
        staged.annotations,
        session=session,
    )

    num_issues = 0
    if "issue_state" in staged.annotations.columns:
        num_issues = client.create_task_issues(
            task_id, staged.annotations, session=session
        )

    if options.mark_all_deleted:
        client.mark_frames_deleted(
            task_id, plan.image_names | plan.deleted_names, session=session
        )
    elif plan.deleted_names:
        client.mark_frames_deleted(task_id, plan.deleted_names, session=session)

    if options.complete:
        client.complete_task(task_id)

    return task_id, num_shapes, num_issues


def upload_dataset(client: CvatClient, request: UploadRequest) -> UploadOutcome:
    """Run the full upload chain: S3 → task → annotations → issues → deleted.

    Validates labels, uploads missing images to the project cloud storage,
    creates the CVAT task, uploads annotations, opens issues, marks
    deleted frames, optionally completes the task, and invalidates the
    local annotation cache entry.
    """
    staged = _stage_images(client, request)
    task_id, num_shapes, num_issues = _push_to_cvat(client, request, staged)

    invalidate_local_entry(request.project_id, task_id, request.project_name)

    segment_size = request.options.segment_size
    num_jobs = (len(staged.task_image_names) + segment_size - 1) // segment_size
    outcome = UploadOutcome(
        task_id=task_id,
        task_name=request.task_name,
        images=len(staged.task_image_names),
        deleted=len(request.plan.deleted_names),
        annotations=num_shapes,
        issues=num_issues,
        jobs=num_jobs,
    )
    logger.info(
        f"Задача создана: id={outcome.task_id}, "
        f"имя={outcome.task_name!r}, "
        f"изображений={outcome.images}, "
        f"удалённых={outcome.deleted}, "
        f"аннотаций={outcome.annotations}, "
        f"issues={outcome.issues}, "
        f"jobs≈{outcome.jobs} (segment_size={segment_size})",
    )
    logger.info(f"URL: {client.host}/tasks/{outcome.task_id}")
    return outcome

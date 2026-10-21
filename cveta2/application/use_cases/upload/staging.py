"""Validate project labels and stage the intended image bytes in storage."""

from collections.abc import Sequence

from loguru import logger

from cveta2.application.client import ApplicationClient as CvatClient
from cveta2.application.use_cases.upload.types import (
    UPLOAD_REQUIRED_COLUMNS,
    UploadDependencies,
    UploadRequest,
    _StagedUpload,
)
from cveta2.domain.errors import Cveta2Error, LabelsMismatchError
from cveta2.domain.output import preview_names
from cveta2.domain.paths import build_s3_key


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


def _warn_missing_images(missing: list[str]) -> None:
    """Log a warning about images not found locally."""
    if not missing:
        return
    logger.warning(
        f"{len(missing)} изображений не найдено локально: {preview_names(missing)}",
    )


def _stage_images(
    client: CvatClient,
    request: UploadRequest,
    pinned_server_files: dict[str, str] | None = None,
    *,
    deps: UploadDependencies,
) -> _StagedUpload:
    """Validate labels, upload local images to S3, enrich annotation rows.

    *pinned_server_files* replaces the freshly computed name → server-file
    mapping when resuming, so images the first run had not uploaded yet
    keep the folder that run assigned them rather than today's month.
    """
    plan = request.plan
    upload_labels = (
        sorted(
            label
            for label in plan.annotations["instance_label"].dropna().unique()
            if str(label).strip()
        )
        if "instance_label" in plan.annotations
        else []
    )
    validate_labels(client, request.project_id, request.project_name, upload_labels)

    all_image_names = list(dict.fromkeys([*plan.image_names, *plan.deleted_names]))

    found_images, missing = deps.files.resolve_images(
        all_image_names, request.options.search_dirs
    )
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

    name_to_server_file, existing_keys = deps.storage.mapping(
        cs_info,
        all_image_names,
        pinned=pinned_server_files,
    )

    annotation_rows = plan.annotations
    if annotation_rows.empty:
        annotation_rows = annotation_rows.reindex(
            columns=[
                *annotation_rows.columns,
                *[
                    column
                    for column in UPLOAD_REQUIRED_COLUMNS
                    if column not in annotation_rows
                ],
            ]
        )
    annotations = deps.files.enrich_dataframe_paths(
        annotation_rows, cs_info, found_images, name_to_server_file
    )

    if found_images:
        stats = deps.storage.upload(
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
        if stats.failed:
            # Every name goes into server_files regardless, so a file that
            # never reached S3 would still be bound into the task and only
            # surface as a processing failure — after the task exists.
            raise Cveta2Error(
                f"Ошибка: {stats.failed} изображений не загрузились на S3. "
                f"Задача не создана; повторите команду, уже загруженные "
                f"изображения будут пропущены."
            )

    _warn_missing_images(missing)
    unreachable = [
        name
        for name in missing
        if build_s3_key(cs_info.prefix, name_to_server_file[name]) not in existing_keys
    ]
    if unreachable:
        raise Cveta2Error(
            f"Ошибка: {len(unreachable)} изображений нет ни локально, ни на S3: "
            f"{preview_names(unreachable)}. Задача не создана."
        )

    task_image_names = [
        build_s3_key(cs_info.prefix, name_to_server_file[n]) for n in all_image_names
    ]
    return _StagedUpload(
        cs_info=cs_info,
        annotations=annotations,
        task_image_names=task_image_names,
        name_to_server_file=name_to_server_file,
    )

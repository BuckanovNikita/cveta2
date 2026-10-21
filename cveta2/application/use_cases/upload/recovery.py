"""Reconcile durable upload intent with CVAT before replaying any writes."""

from collections import Counter
from pathlib import PurePosixPath

import pandas as pd
from loguru import logger

from cveta2.application.client import ApplicationClient as CvatClient
from cveta2.application.client.session import TaskWriteSession
from cveta2.application.client.upload_mapping import (
    ShapeBuildResult,
    build_upload_shapes,
)
from cveta2.application.use_cases.upload.staging import _stage_images
from cveta2.application.use_cases.upload.types import (
    UploadDependencies,
    UploadOutcome,
    UploadRequest,
    _StagedUpload,
)
from cveta2.domain.errors import CvatApiError, Cveta2Error
from cveta2.domain.upload import (
    UploadManifest,
    compute_mapping_identity,
    upload_annotation_mask,
)

_HTTP_NOT_FOUND = 404


def _verify_existing_shapes(
    task_id: int,
    annotations: pd.DataFrame,
    session: TaskWriteSession,
) -> int:
    """Verify the remote semantic shape multiset without performing writes."""
    annotation_rows = annotations[upload_annotation_mask(annotations)]
    built = ShapeBuildResult()
    if not annotation_rows.empty:
        built = build_upload_shapes(
            annotation_rows,
            session.name_to_frame,
            {label.name: label.id for label in session.labels},
        )
    if built.unknown_images or built.unknown_labels:
        raise Cveta2Error(
            f"Задача {task_id}: изображения или метки не совпадают; продолжить нельзя."
        )
    existing = session.api.get_task_annotations(task_id).shapes
    if existing:
        expected = Counter(
            (shape.type, shape.frame, shape.label_id, tuple(shape.points))
            for shape in built.shapes
        )
        actual = Counter(
            (shape.type, shape.frame, shape.label_id, tuple(shape.points))
            for shape in existing
        )
        properties_match = all(
            not shape.occluded
            and shape.z_order == 0
            and shape.rotation == 0
            and not shape.attributes
            for shape in existing
        )
        if actual != expected or not properties_match:
            raise Cveta2Error(
                f"Задача {task_id}: аннотации не совпадают с намерением загрузки "
                "(частичные или изменённые данные). Запись не повторяется."
            )
        logger.info(
            f"Задача {task_id}: подтверждены {len(existing)} аннотаций, пропускаем"
        )
        return len(existing)
    return 0


def _ensure_annotations(
    client: CvatClient,
    task_id: int,
    staged: _StagedUpload,
    session: TaskWriteSession,
    resuming: bool,  # noqa: FBT001
) -> int:
    """Reuse only a verified complete shape multiset; never guess from count."""
    if resuming:
        existing = _verify_existing_shapes(task_id, staged.annotations, session)
        if existing:
            logger.info(
                f"Задача {task_id}: подтверждены {existing} аннотаций, пропускаем"
            )
            return existing
    return client.upload_task_annotations(task_id, staged.annotations, session=session)


def _ensure_task(
    client: CvatClient,
    request: UploadRequest,
    staged: _StagedUpload,
    manifest: UploadManifest,
    *,
    deps: UploadDependencies,
) -> int:
    """Return the task holding this upload's frames, creating it if needed.

    The manifest says which task a previous run created; CVAT says what
    actually happened to it. Matching frame count and identities permit
    reuse when processing finished after a lost reply. An empty task does
    not prove attachment failed: processing may still be running, so it
    stops without deletion or replay. Partial or conflicting frames also
    stop; only a confirmed missing task can safely be recreated.
    """
    expected = len(staged.task_image_names)

    def create() -> int:
        """Persist pending intent and checkpoint the task ID before attachment."""
        if manifest.creation_pending and manifest.task_id is None:
            raise Cveta2Error(
                "Результат создания задачи неизвестен. Проверьте CVAT вручную; "
                "автоматическое создание новой задачи небезопасно."
            )
        # A confirmed missing old task is not the identity of its replacement.
        # A lost create reply must leave an unknown ID, never the old one.
        manifest.task_id = None
        manifest.creation_pending = True
        deps.manifests.save(manifest, required=True)
        return client.create_upload_task(
            project_id=request.project_id,
            name=request.task_name,
            image_names=staged.task_image_names,
            cloud_storage_id=staged.cs_info.id,
            segment_size=request.options.segment_size,
            image_quality=request.options.image_quality,
            on_created=lambda new_id: _record_task_id(manifest, new_id, deps=deps),
        )

    if manifest.task_id is None:
        return create()

    try:
        task = client.get_task(manifest.task_id)
        if task.project_id != request.project_id:
            raise Cveta2Error(
                f"Ошибка: задача {manifest.task_id} принадлежит проекту "
                f"{task.project_id}, а загрузка — проекту {request.project_id}. "
                "Продолжить нельзя; задача не изменена."
            )
        size = client.get_task_size(manifest.task_id)
    except CvatApiError as e:
        if e.status_code != _HTTP_NOT_FOUND:
            raise
        # The likeliest manual intervention: the stranded task was deleted
        # in the CVAT UI. That is the state a fresh task is for, so there is
        # nothing to warn about beyond saying what happened.
        logger.info(
            f"Задача {manifest.task_id} больше не существует в CVAT — создаём новую."
        )
        return create()
    if size == expected:
        actual_names = [
            frame.name
            for frame in client.open_task_session(manifest.task_id).data_meta.frames
        ]
        if not _frames_match(
            actual_names, staged.task_image_names, staged.cs_info.prefix
        ):
            raise Cveta2Error(
                f"Задача {manifest.task_id}: порядок или имена кадров изменены; "
                "запись запрещена."
            )
        logger.info(
            f"Продолжаем задачу {manifest.task_id}: {size} изображений уже привязаны."
        )
        return manifest.task_id
    if size == 0:
        raise Cveta2Error(
            f"Задача {manifest.task_id} пока без изображений; результат привязки "
            "неизвестен. Дождитесь обработки или проверьте задачу вручную. "
            "Задача не удалена, повторная запись не выполняется."
        )
    raise Cveta2Error(
        f"Ошибка: задача {manifest.task_id} содержит {size} изображений, "
        f"а загрузка рассчитана на {expected}. Продолжить нельзя."
    )


def _record_task_id(
    manifest: UploadManifest, task_id: int, *, deps: UploadDependencies
) -> None:
    """Persist the new task id before the long frame-attach step runs."""
    manifest.task_id = task_id
    deps.manifests.save(manifest, required=True)


def _resume_manifest(
    request: UploadRequest, fingerprint: str, *, host: str, deps: UploadDependencies
) -> UploadManifest:
    """Load the manifest ``--resume`` was asked to continue, or explain why not.

    A missing manifest is reported against whatever unfinished uploads the
    project does have, because the likely mistake is resuming with a
    different CSV or label selection — and "nothing to resume" alone would
    leave the user guessing which one.
    """
    manifest = deps.manifests.load(request.project_id, fingerprint, host=host)
    if manifest is not None:
        if (
            not manifest.intent_complete
            or manifest.mapping_identity != compute_mapping_identity(manifest)
        ):
            raise Cveta2Error(
                "Состояние загрузки не содержит полного намерения; "
                "продолжение небезопасно."
            )
        return manifest
    others = deps.manifests.list_for_project(request.project_id, host=host)
    if not others:
        raise Cveta2Error(
            f"Ошибка: незавершённых загрузок для проекта "
            f"{request.project_name!r} не найдено — нечего продолжать."
        )
    listed = "\n".join(f"  - {other.describe()}" for other in others)
    raise Cveta2Error(
        f"Ошибка: для этого набора изображений и меток незавершённой "
        f"загрузки нет. Незавершённые загрузки проекта "
        f"{request.project_name!r}:\n{listed}\n"
        f"Запустите --resume с тем же CSV и теми же --labels, что и в тот раз."
    )


def _fresh_manifest(
    client: CvatClient,
    request: UploadRequest,
    fingerprint: str,
    *,
    deps: UploadDependencies,
) -> tuple[_StagedUpload, UploadManifest]:
    """Stage images for a new upload and record what it decided."""
    existing = deps.manifests.load(request.project_id, fingerprint, host=client.host)
    if existing is not None and (
        existing.task_id is not None or existing.creation_pending
    ):
        raise Cveta2Error(
            f"Найдена незавершённая загрузка этого набора "
            f"(задача {existing.task_id}); повторное создание запрещено. "
            f"Чтобы продолжить её, повторите команду с --resume."
        )
    staged = _stage_images(client, request, deps=deps)
    manifest = deps.manifests.new(
        dataset_path=request.dataset_path,
        fingerprint=fingerprint,
        project_id=request.project_id,
        task_name=request.task_name,
        cs_info=staged.cs_info,
        name_to_server_file=staged.name_to_server_file,
        task_image_names=staged.task_image_names,
        host=client.host,
        intent_complete=True,
    )
    deps.manifests.save(manifest, required=True)
    return staged, manifest


def _completed_outcome(
    request: UploadRequest, manifest: UploadManifest
) -> UploadOutcome:
    """Return the completed remote task without replaying stale bookkeeping."""
    if manifest.task_id is None or manifest.completed_counts is None:
        raise Cveta2Error(
            "Состояние завершённой загрузки повреждено; запись запрещена."
        )
    shapes, issues, jobs = manifest.completed_counts
    logger.info(
        f"Загрузка уже завершена: задача {manifest.task_id}; запись не повторяется."
    )
    return UploadOutcome(
        manifest.task_id,
        manifest.task_name,
        len(manifest.task_image_names),
        len(request.plan.deleted_names),
        shapes,
        issues,
        jobs,
    )


def _frames_match(actual: list[str], intended: list[str], prefix: str) -> bool:
    """Verify available directory identity, allowing cloud prefix omission."""
    if len(actual) != len(intended):
        return False
    expected = [str(PurePosixPath(name)) for name in intended]
    cloud_prefix = str(PurePosixPath(prefix.strip("/"))) if prefix.strip("/") else ""
    basenames = Counter(PurePosixPath(name).name for name in expected)
    shortened = False
    for raw_name, expected_name in zip(actual, expected, strict=True):
        name = str(PurePosixPath(raw_name))
        if "/" not in name:
            basename = PurePosixPath(expected_name).name
            if name != basename or basenames[basename] != 1:
                return False
            shortened = shortened or name != expected_name
        elif name != expected_name:
            relative = (
                expected_name.removeprefix(f"{cloud_prefix}/")
                if cloud_prefix
                else expected_name
            )
            if name != relative:
                return False
    if shortened:
        logger.warning(
            "CVAT сообщает только имена файлов без каталогов; порядок проверен, "
            "но исходный путь каждого файла подтвердить невозможно."
        )
    return True


def _preflight_resume_target(
    client: CvatClient,
    request: UploadRequest,
    manifest: UploadManifest,
) -> None:
    """Validate known target identity and contents before external staging writes."""
    if manifest.task_id is None:
        raise Cveta2Error("ID задачи неизвестен; продолжение запрещено.")
    try:
        task = client.get_task(manifest.task_id)
        size = client.get_task_size(manifest.task_id)
    except CvatApiError as exc:
        if exc.status_code == _HTTP_NOT_FOUND:
            return
        raise
    if task.project_id != request.project_id:
        raise Cveta2Error(
            f"Задача {manifest.task_id} принадлежит проекту {task.project_id}, "
            f"а загрузка — проекту {request.project_id}. Продолжение запрещено."
        )
    session = client.open_task_session(manifest.task_id)
    actual_names = [frame.name for frame in session.data_meta.frames]
    if size != len(manifest.task_image_names) or not _frames_match(
        actual_names,
        manifest.task_image_names,
        manifest.cs_info.prefix,
    ):
        raise Cveta2Error(
            f"Задача {manifest.task_id}: кадры не совпадают или привязка "
            "ещё не завершена; запись запрещена."
        )
    _verify_existing_shapes(manifest.task_id, request.plan.annotations, session)

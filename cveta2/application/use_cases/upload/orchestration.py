"""Execute the upload stages in their required recovery checkpoint order."""

from loguru import logger

from cveta2.application.client import ApplicationClient as CvatClient
from cveta2.application.use_cases.upload.planning import request_fingerprint
from cveta2.application.use_cases.upload.recovery import (
    _completed_outcome,
    _ensure_annotations,
    _ensure_task,
    _fresh_manifest,
    _preflight_resume_target,
    _resume_manifest,
)
from cveta2.application.use_cases.upload.staging import _stage_images
from cveta2.application.use_cases.upload.types import (
    UploadDependencies,
    UploadOutcome,
    UploadRequest,
    _StagedUpload,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.upload import UploadManifest, validate_upload_boxes


def _push_to_cvat(
    client: CvatClient,
    request: UploadRequest,
    staged: _StagedUpload,
    manifest: UploadManifest,
    *,
    deps: UploadDependencies,
) -> tuple[int, int, int]:
    """Create the task and push annotations, issues and deleted frames.

    Returns ``(task_id, num_shapes, num_issues)``.
    """
    plan, options = request.plan, request.options
    task_id = _ensure_task(client, request, staged, manifest, deps=deps)
    session = client.open_task_session(task_id)

    num_shapes = _ensure_annotations(client, task_id, staged, session, request.resume)

    num_issues = 0
    if "issue_state" in staged.annotations.columns:
        num_issues = client.create_task_issues(
            task_id,
            staged.annotations,
            session=session,
            skip_existing=request.resume,
        )

    if options.mark_all_deleted:
        client.mark_frames_deleted(
            task_id, {*plan.image_names, *plan.deleted_names}, session=session
        )
    elif plan.deleted_names:
        client.mark_frames_deleted(task_id, set(plan.deleted_names), session=session)

    if options.complete:
        client.complete_task(task_id)

    return task_id, num_shapes, num_issues


def upload_dataset(
    client: CvatClient, request: UploadRequest, *, deps: UploadDependencies
) -> UploadOutcome:
    """Run the full upload chain: S3 → task → annotations → issues → deleted.

    Validates labels, uploads missing images to the project cloud storage,
    creates the CVAT task, uploads annotations, opens issues, marks
    deleted frames, optionally completes the task, and invalidates the
    local annotation cache entry.

    A manifest of the run is written before CVAT is touched and updated the
    moment a task id exists, so ``resume=True`` can continue an upload that
    died partway.  It is removed once the upload finishes.
    """
    validate_upload_boxes(request.plan.annotations)
    fingerprint = request_fingerprint(request)
    if request.resume:
        manifest = _resume_manifest(request, fingerprint, host=client.host, deps=deps)
        if manifest.completed_counts is not None:
            deps.manifests.delete(
                request.project_id,
                fingerprint,
                host=client.host,
                task_id=manifest.task_id,
            )
            return _completed_outcome(request, manifest)
        if manifest.creation_pending and manifest.task_id is None:
            raise Cveta2Error(
                "Результат создания задачи неизвестен; проверьте CVAT вручную. "
                "Новая задача не создаётся."
            )
        current_storage = client.detect_project_cloud_storage(request.project_id)
        if current_storage != manifest.cs_info:
            raise Cveta2Error(
                "Cloud storage проекта изменён; продолжение запрещено до записи."
            )
        if manifest.task_id is not None:
            _preflight_resume_target(client, request, manifest)
        staged = _stage_images(client, request, manifest.name_to_server_file, deps=deps)
    else:
        existing = deps.manifests.load(
            request.project_id, fingerprint, host=client.host
        )
        if existing is not None and existing.completed_counts is not None:
            deps.manifests.delete(
                request.project_id,
                fingerprint,
                host=client.host,
                task_id=existing.task_id,
            )
            return _completed_outcome(request, existing)
        staged, manifest = _fresh_manifest(client, request, fingerprint, deps=deps)

    task_id, num_shapes, num_issues = _push_to_cvat(
        client, request, staged, manifest, deps=deps
    )

    deps.invalidate(request.project_id, task_id, request.project_name)

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
    manifest.completed_counts = (num_shapes, num_issues, num_jobs)
    deps.manifests.save(manifest)
    deps.manifests.delete(
        request.project_id, fingerprint, host=client.host, task_id=task_id
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

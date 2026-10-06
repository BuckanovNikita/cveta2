"""Upload pipeline orchestration: filtering, S3 upload, task creation chain.

Pure orchestration over :class:`CvatClient` — no prompts, no ``sys.exit``.
The CLI layer resolves interactive inputs (label selection, task name)
before calling in; the public API calls in directly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2._client.assembly import ShapeBuildResult, build_upload_shapes
from cveta2.config import resolve_images_cache_dir
from cveta2.exceptions import CvatApiError, Cveta2Error, LabelsMismatchError
from cveta2.image_uploader import S3Uploader, build_server_file_mapping, resolve_images
from cveta2.s3_utils import build_s3_key
from cveta2.services.output import (
    CSV_READ_OPTIONS,
    enrich_dataframe_paths,
    preview_names,
)
from cveta2.task_cache import invalidate_local_entry
from cveta2.upload_manifest import (
    UploadManifest,
    compute_fingerprint,
    compute_mapping_identity,
    delete_manifest,
    list_manifests,
    load_manifest,
    new_manifest,
    save_manifest,
    validate_upload_boxes,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cveta2._client_ops.session import TaskWriteSession
    from cveta2.client import CvatClient
    from cveta2.image_downloader import CloudStorageInfo

# A module-level constant is never mutated, so the wording stays out of the
# mutation gate: no test has to assert prose to keep this literal honest.
_NOTHING_TO_UPLOAD = "Ошибка: после фильтрации не осталось изображений."

_HTTP_NOT_FOUND = 404


UPLOAD_REQUIRED_COLUMNS: set[str] = {"image_name", "instance_label"}
"""Columns an upload CSV must carry, shared by the CLI and the api layer."""


@dataclass(frozen=True)
class UploadPlan:
    """Resolved upload inputs: filtered rows and ordered image-name lists.

    Name lists keep CSV row order (deduped by first occurrence) so the
    created CVAT task shows frames in the same order as the source CSV.
    """

    annotations: pd.DataFrame
    image_names: list[str]
    deleted_names: list[str]


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
    dataset_path: str = ""
    labels: tuple[str, ...] = ()
    resume: bool = False


@dataclass(frozen=True)
class _StagedUpload:
    """Result of the S3 staging step: storage info and enriched rows."""

    cs_info: CloudStorageInfo
    annotations: pd.DataFrame
    task_image_names: list[str]
    name_to_server_file: dict[str, str]


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
    ip_df = pd.read_csv(ip_path, **CSV_READ_OPTIONS)
    if "image_name" not in ip_df.columns:
        return set()
    names: set[str] = set(ip_df["image_name"].dropna().unique())
    logger.info(
        f"Исключено {len(names)} изображений ({len(ip_df)} строк) из in_progress.csv"
    )
    return names


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
    *,
    config_path: Path | None = None,
) -> list[Path]:
    """Build list of directories to search for image files.

    Resolves the project's image cache the same way ``fetch`` and
    ``s3-sync`` do: an explicit ``image_cache`` entry first, then
    ``cache.images_root``.  Reading only the explicit entry, as this used
    to, meant a project configured solely through the global root
    uploaded nothing but what was already on S3.
    """
    if isinstance(image_dirs, (str, Path)):
        image_dirs = [image_dirs]
    dirs: list[Path] = [Path(d).resolve() for d in (image_dirs or [])]
    cache_dir = resolve_images_cache_dir(project_name, config_path)
    if cache_dir is not None:
        dirs.append(cache_dir)
    if not dirs:
        logger.warning(
            "Не указан --image-dir и не настроены ни image_cache, "
            f"ни cache.images_root для проекта {project_name!r}. "
            "Будут загружены только изображения, "
            "уже находящиеся на S3.",
        )
    return dirs


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
    annotations = enrich_dataframe_paths(
        annotation_rows, cs_info, found_images, name_to_server_file
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


def _verify_existing_shapes(
    task_id: int,
    annotations: pd.DataFrame,
    session: TaskWriteSession,
) -> int:
    """Verify the remote semantic shape multiset without performing writes."""
    annotation_rows = annotations
    if "instance_shape" in annotation_rows:
        annotation_rows = annotation_rows[
            annotation_rows["instance_shape"].ne("deleted")
        ]
    if "instance_label" in annotation_rows:
        annotation_rows = annotation_rows[
            annotation_rows["instance_label"].fillna("").astype(str).str.strip().ne("")
        ]
    else:
        annotation_rows = annotation_rows.iloc[:0]
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
        if manifest.creation_pending and manifest.task_id is None:
            raise Cveta2Error(
                "Результат создания задачи неизвестен. Проверьте CVAT вручную; "
                "автоматическое создание новой задачи небезопасно."
            )
        # A confirmed missing old task is not the identity of its replacement.
        # A lost create reply must leave an unknown ID, never the old one.
        manifest.task_id = None
        manifest.creation_pending = True
        save_manifest(manifest, required=True)
        return client.create_upload_task(
            project_id=request.project_id,
            name=request.task_name,
            image_names=staged.task_image_names,
            cloud_storage_id=staged.cs_info.id,
            segment_size=request.options.segment_size,
            image_quality=request.options.image_quality,
            on_created=lambda new_id: _record_task_id(manifest, new_id),
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


def _record_task_id(manifest: UploadManifest, task_id: int) -> None:
    """Persist the new task id before the long frame-attach step runs."""
    manifest.task_id = task_id
    save_manifest(manifest, required=True)


def _push_to_cvat(
    client: CvatClient,
    request: UploadRequest,
    staged: _StagedUpload,
    manifest: UploadManifest,
) -> tuple[int, int, int]:
    """Create the task and push annotations, issues and deleted frames.

    Returns ``(task_id, num_shapes, num_issues)``.
    """
    plan, options = request.plan, request.options
    task_id = _ensure_task(client, request, staged, manifest)
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


def _resume_manifest(
    request: UploadRequest, fingerprint: str, *, host: str
) -> UploadManifest:
    """Load the manifest ``--resume`` was asked to continue, or explain why not.

    A missing manifest is reported against whatever unfinished uploads the
    project does have, because the likely mistake is resuming with a
    different CSV or label selection — and "nothing to resume" alone would
    leave the user guessing which one.
    """
    manifest = load_manifest(request.project_id, fingerprint, host=host)
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
    others = list_manifests(request.project_id, host=host)
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
) -> tuple[_StagedUpload, UploadManifest]:
    """Stage images for a new upload and record what it decided."""
    existing = load_manifest(request.project_id, fingerprint, host=client.host)
    if existing is not None and (
        existing.task_id is not None or existing.creation_pending
    ):
        raise Cveta2Error(
            f"Найдена незавершённая загрузка этого набора "
            f"(задача {existing.task_id}); повторное создание запрещено. "
            f"Чтобы продолжить её, повторите команду с --resume."
        )
    staged = _stage_images(client, request)
    manifest = new_manifest(
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
    save_manifest(manifest, required=True)
    return staged, manifest


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


def upload_dataset(client: CvatClient, request: UploadRequest) -> UploadOutcome:
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
        manifest = _resume_manifest(request, fingerprint, host=client.host)
        if manifest.completed_counts is not None:
            delete_manifest(
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
        staged = _stage_images(client, request, manifest.name_to_server_file)
    else:
        existing = load_manifest(request.project_id, fingerprint, host=client.host)
        if existing is not None and existing.completed_counts is not None:
            delete_manifest(
                request.project_id,
                fingerprint,
                host=client.host,
                task_id=existing.task_id,
            )
            return _completed_outcome(request, existing)
        staged, manifest = _fresh_manifest(client, request, fingerprint)

    task_id, num_shapes, num_issues = _push_to_cvat(client, request, staged, manifest)

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
    manifest.completed_counts = (num_shapes, num_issues, num_jobs)
    save_manifest(manifest)
    delete_manifest(request.project_id, fingerprint, host=client.host, task_id=task_id)
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

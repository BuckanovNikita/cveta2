"""CVAT client logic: connect, fetch annotations, extract shapes."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import pandas as pd
from cvat_sdk import make_client
from cvat_sdk.api_client.exceptions import ApiException
from loguru import logger
from tqdm import tqdm

from cveta2._client.context import _TaskContext
from cveta2._client.extractors import _collect_shapes
from cveta2._client.mapping import _build_label_maps
from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.config import CvatConfig
from cveta2.exceptions import ProjectNotFoundError, TaskNotFoundError
from cveta2.image_downloader import (
    CloudStorageInfo,
    DownloadStats,
    ImageDownloader,
    S3Syncer,
    parse_cloud_storage,
)
from cveta2.models import (
    CSV_COLUMNS,
    AnnotationRecord,
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    LabelInfo,
    ProjectAnnotations,
    ProjectInfo,
    TaskAnnotations,
    TaskInfo,
)

_DATA_PROCESSING_TIMEOUT = int(os.environ.get("CVETA2_DATA_TIMEOUT", "60"))
"""Max seconds to wait for CVAT to finish processing cloud storage data.

Configurable via ``CVETA2_DATA_TIMEOUT`` env var (default 60).
"""

_HTTP_5XX_MIN = 500
_HTTP_5XX_MAX = 600


@dataclass(frozen=True)
class _FetchAnnotationsOptions:
    """Options for _fetch_annotations (filters + display/hint)."""

    completed_only: bool = False
    ignore_task_ids: set[int] | None = None
    silent_task_ids: set[int] | None = None
    task_selector: list[int | str] | None = None
    host: str = ""
    project_name: str = ""


@dataclass(frozen=True)
class FetchContext:
    """Prepared context for per-task annotation fetching.

    Returned by :meth:`CvatClient.prepare_fetch`; passed to
    :meth:`CvatClient.fetch_one_task` for each task in the loop.
    """

    tasks: list[TaskInfo]
    label_names: dict[int, str]
    attr_names: dict[int, str]
    host: str = ""
    project_name: str = ""


def _log_task_5xx_skip(
    task: TaskInfo,
    host: str,
    project_name: str,
    status: int,
    e: ApiException,
) -> None:
    """Log 5xx error and ignore-command hint for a skipped task."""
    task_link = (
        f"{host.rstrip('/')}/tasks/{task.id}"
        if host
        else f"task_id={task.id} {task.name!r}"
    )
    logger.error(f"CVAT server error (HTTP {status}) for task {task_link}: {e}")
    if project_name:
        logger.info(
            f"Чтобы пропустить задачу при следующем запуске: "
            f"cveta2 ignore --project {project_name!r} --add {task.id}"
        )
    else:
        logger.info(
            f"Чтобы пропустить задачу при следующем запуске: "
            f"cveta2 ignore --project <имя_проекта> --add {task.id}"
        )


def _filter_tasks_for_fetch(
    tasks: list[TaskInfo],
    options: _FetchAnnotationsOptions,
) -> list[TaskInfo]:
    """Apply ignore list, task selector, completed_only; return filtered list."""
    if options.ignore_task_ids:
        skipped = [t for t in tasks if t.id in options.ignore_task_ids]
        silent_ids = options.silent_task_ids or set()
        logged = [t for t in skipped if t.id not in silent_ids]
        if logged:
            logger.warning(f"Пропускаем {len(logged)} задач(а) из ignore-списка:")
            for t in logged:
                logger.warning(f"  - #{t.id} {t.name!r} (обновлена: {t.updated_date})")
        tasks = [t for t in tasks if t.id not in options.ignore_task_ids]
    if options.task_selector is not None:
        tasks = CvatClient.resolve_task_selectors(tasks, options.task_selector)
        names = ", ".join(f"{t.name!r} (id={t.id})" for t in tasks)
        logger.info(f"Selected {len(tasks)} task(s): {names}")
    if options.completed_only:
        tasks = [t for t in tasks if t.status == "completed"]
        logger.trace(f"Filtered to {len(tasks)} completed task(s)")
    return tasks


def _task_to_records(
    task: TaskInfo,
    data_meta: RawDataMeta,
    annotations: RawAnnotations,
    label_names: dict[int, str],
    attr_names: dict[int, str],
) -> tuple[list[AnnotationRecord], list[DeletedImage]]:
    """Build annotation records and deleted list for one task."""
    ctx = _TaskContext.from_raw(task, data_meta, label_names, attr_names)
    task_annotations = _collect_shapes(annotations.shapes, ctx)
    deleted_ids = set(data_meta.deleted_frames)
    frames = ctx.frames
    task_deleted = [
        DeletedImage(
            task_id=task.id,
            task_name=task.name,
            task_status=task.status,
            task_updated_date=task.updated_date,
            frame_id=fid,
            image_name=(frames[fid].name if fid in frames else "<unknown>"),
            image_width=(frames[fid].width if fid in frames else 0),
            image_height=(frames[fid].height if fid in frames else 0),
            subset=task.subset,
        )
        for fid in data_meta.deleted_frames
    ]
    annotated_ids = {a.frame_id for a in task_annotations}
    task_without = [
        ImageWithoutAnnotations(
            image_name=frame.name,
            image_width=frame.width,
            image_height=frame.height,
            task_id=task.id,
            task_name=task.name,
            task_status=task.status,
            task_updated_date=task.updated_date,
            frame_id=fid,
            subset=task.subset,
        )
        for fid, frame in frames.items()
        if fid not in deleted_ids and fid not in annotated_ids
    ]
    return (
        list(task_annotations) + task_without,
        task_deleted,
    )


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from contextlib import AbstractContextManager
    from pathlib import Path
    from types import TracebackType

    from typing_extensions import Self

    from cveta2._client.dtos import RawAnnotations, RawDataMeta
    from cveta2._client.ports import CvatApiPort


class _SdkClientFactory(Protocol):
    """Protocol for the SDK client factory (e.g. ``cvat_sdk.make_client``).

    The factory must accept keyword arguments (``host`` and
    ``credentials``) and return a context manager that yields an SDK
    client.
    """

    def __call__(self, **kwargs: Any) -> AbstractContextManager[Any]:  # noqa: ANN401
        ...


class CvatClient:
    """High-level CVAT client that fetches bbox annotations.

    Can be used as a context manager to keep the SDK connection open
    across multiple calls::

        with CvatClient(cfg) as client:
            projects = client.list_projects()
            result = client.fetch_annotations(project_id)

    Without the context manager, each public method opens and closes
    its own connection (backward-compatible behaviour).
    """

    def __init__(
        self,
        cfg: CvatConfig | None = None,
        client_factory: _SdkClientFactory | None = None,
        *,
        api: CvatApiPort | None = None,
    ) -> None:
        """Store client configuration and optional API port for DI.

        When *cfg* is ``None``, configuration is loaded automatically
        from environment variables, config file, and built-in preset
        via :meth:`CvatConfig.load`.

        When *api* is provided it is used directly.  Otherwise an
        ``SdkCvatApiAdapter`` is created on the fly from an SDK client
        opened via *client_factory*.
        """
        self._cfg = cfg or CvatConfig.load()
        self._client_factory: _SdkClientFactory = client_factory or make_client
        self._api = api
        # Persistent adapter opened by __enter__, closed by __exit__.
        self._persistent_api: SdkCvatApiAdapter | None = None
        self._sdk_client: Any = None

    # ------------------------------------------------------------------
    # Context manager (optional connection reuse)
    # ------------------------------------------------------------------

    def __enter__(self) -> Self:
        """Open a persistent SDK connection for the lifetime of this block."""
        if self._api is not None:
            # DI api provided -- nothing to open.
            return self
        resolved = self._cfg.ensure_credentials()
        kwargs = self._build_client_kwargs(resolved)
        self._sdk_client = self._client_factory(**kwargs)
        sdk = self._sdk_client.__enter__()
        if resolved.organization:
            sdk.organization_slug = resolved.organization
            logger.trace(f"Using organization: {resolved.organization}")
        self._persistent_api = SdkCvatApiAdapter(sdk)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the persistent SDK connection."""
        self._persistent_api = None
        if self._sdk_client is not None:
            self._sdk_client.__exit__(exc_type, exc_val, exc_tb)
            self._sdk_client = None

    # ------------------------------------------------------------------
    # SDK client lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def _open_sdk_adapter(self) -> Iterator[SdkCvatApiAdapter]:
        """Open an SDK client and yield an adapter wrapping it."""
        resolved = self._cfg.ensure_credentials()
        kwargs = self._build_client_kwargs(resolved)
        with self._client_factory(**kwargs) as sdk_client:
            if resolved.organization:
                sdk_client.organization_slug = resolved.organization
                logger.trace(
                    f"Using organization: {resolved.organization}",
                )
            yield SdkCvatApiAdapter(sdk_client)

    def _get_api(self) -> CvatApiPort | None:
        """Return the best available API port (injected > persistent > None)."""
        return self._api or self._persistent_api

    @contextmanager
    def _api_or_adapter(self) -> Iterator[CvatApiPort]:
        """Yield the best API port (injected/persistent or a new SDK adapter)."""
        api = self._get_api()
        if api is not None:
            yield api
        else:
            with self._open_sdk_adapter() as adapter:
                yield adapter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_projects(self) -> list[ProjectInfo]:
        """Fetch list of projects from CVAT (id and name)."""
        with self._api_or_adapter() as source:
            return source.list_projects()

    def list_project_tasks(self, project_id: int) -> list[TaskInfo]:
        """Fetch the list of tasks for a project from CVAT."""
        with self._api_or_adapter() as source:
            return source.get_project_tasks(project_id)

    def get_project_labels(self, project_id: int) -> list[LabelInfo]:
        """Fetch label definitions for a project from CVAT."""
        with self._api_or_adapter() as source:
            return source.get_project_labels(project_id)

    def count_label_usage(self, project_id: int) -> dict[int, int]:
        """Count annotations per label across all project tasks.

        Returns a mapping ``{label_id: annotation_count}``.
        Used to warn before label deletion.
        """
        with self._api_or_adapter() as source:
            tasks = source.get_project_tasks(project_id)
            counts: dict[int, int] = {}
            skipped: list[int] = []
            for task in tqdm(
                tasks, desc="Checking annotations", unit="task", leave=False
            ):
                try:
                    annotations = source.get_task_annotations(task.id)
                except ApiException:
                    logger.warning(
                        f"Не удалось получить аннотации задачи {task.id},"
                        " подсчёт меток может быть неполным",
                    )
                    skipped.append(task.id)
                    continue
                for shape in annotations.shapes:
                    counts[shape.label_id] = counts.get(shape.label_id, 0) + 1
            if skipped:
                logger.warning(f"Пропущено задач при подсчёте меток: {skipped}")
            return counts

    def update_project_labels(
        self,
        project_id: int,
        *,
        add: list[str] | None = None,
        rename: dict[int, str] | None = None,
        delete: list[int] | None = None,
        recolor: dict[int, str] | None = None,
    ) -> None:
        """Update project labels via CVAT PATCH API.

        Parameters
        ----------
        project_id:
            CVAT project ID.
        add:
            Label names to create (CVAT assigns IDs and colors).
        rename:
            Mapping ``{label_id: new_name}`` for labels to rename.
        delete:
            Label IDs to delete.  **Destroys all annotations using
            those labels permanently.**
        recolor:
            Mapping ``{label_id: new_hex_color}`` for labels to
            change color (e.g. ``"#ff0000"``).

        Requires an active context manager.

        """
        sdk = self._require_sdk("update_project_labels")
        from cvat_sdk.api_client import models as cvat_models  # noqa: PLC0415

        patch_labels: list[cvat_models.PatchedLabelRequest] = [
            cvat_models.PatchedLabelRequest(name=name) for name in (add or [])
        ]
        patch_labels.extend(
            cvat_models.PatchedLabelRequest(id=lid, name=new_name)
            for lid, new_name in (rename or {}).items()
        )
        patch_labels.extend(
            cvat_models.PatchedLabelRequest(id=lid, deleted=True)
            for lid in (delete or [])
        )
        patch_labels.extend(
            cvat_models.PatchedLabelRequest(id=lid, color=color)
            for lid, color in (recolor or {}).items()
        )
        if not patch_labels:
            return
        sdk.api_client.projects_api.partial_update(
            project_id,
            patched_project_write_request=cvat_models.PatchedProjectWriteRequest(
                labels=patch_labels,
            ),
        )

    def resolve_project_id(
        self,
        project_spec: int | str,
        *,
        cached: list[ProjectInfo] | None = None,
    ) -> int:
        """Resolve project id from numeric id or project name.

        If project_spec is int or digit string, returns it as int.
        If it is a name, looks in cached list first, then via API.
        """
        if isinstance(project_spec, int):
            return project_spec
        s = str(project_spec).strip()
        if s.isdigit():
            return int(s)
        search = s.casefold()
        if cached:
            for p in cached:
                if (p.name or "").casefold() == search:
                    return p.id
        projects = self.list_projects()
        for p in projects:
            if (p.name or "").casefold() == search:
                return p.id
        raise ProjectNotFoundError(f"Project not found: {s!r}")

    def fetch_annotations(
        self,
        project_id: int,
        *,
        completed_only: bool = False,
        ignore_task_ids: set[int] | None = None,
        task_selector: list[int | str] | None = None,
        project_name: str = "",
    ) -> ProjectAnnotations:
        """Fetch all bbox annotations and deleted images from a project.

        If ``completed_only`` is True, only completed tasks are processed.
        Tasks whose IDs are in ``ignore_task_ids`` are silently skipped.
        If ``task_selector`` is given (list of task IDs or names), only
        matching tasks are processed.
        """
        options = _FetchAnnotationsOptions(
            completed_only=completed_only,
            ignore_task_ids=ignore_task_ids,
            task_selector=task_selector,
            host=(self._cfg.host or ""),
            project_name=project_name,
        )
        return self.fetch_with_options(project_id, options)

    def fetch_with_options(
        self,
        project_id: int,
        options: _FetchAnnotationsOptions,
    ) -> ProjectAnnotations:
        """Fetch annotations using pre-built *options*."""
        with self._api_or_adapter() as source:
            return self._fetch_annotations(source, project_id, options)

    def prepare_fetch(
        self,
        project_id: int,
        *,
        completed_only: bool = False,
        ignore_task_ids: set[int] | None = None,
        task_selector: list[int | str] | None = None,
        project_name: str = "",
    ) -> FetchContext:
        """Prepare fetch context: get task list, labels, apply filters.

        The returned :class:`FetchContext` holds the filtered task list
        and label maps.  Pass it to :meth:`fetch_one_task` for each task.
        """
        options = _FetchAnnotationsOptions(
            completed_only=completed_only,
            ignore_task_ids=ignore_task_ids,
            task_selector=task_selector,
            host=(self._cfg.host or ""),
            project_name=project_name,
        )
        return self.prepare_fetch_options(project_id, options)

    def prepare_fetch_options(
        self,
        project_id: int,
        options: _FetchAnnotationsOptions,
    ) -> FetchContext:
        """Prepare fetch context using pre-built *options*."""
        with self._api_or_adapter() as source:
            return self._prepare_fetch(source, project_id, options)

    # ------------------------------------------------------------------
    # Core annotation logic (single code path for all API backends)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_one_task_selector(
        tasks: list[TaskInfo],
        selector: int | str,
    ) -> TaskInfo:
        """Resolve a single task selector (ID or name) to a task.

        Numeric strings and ints match by task ID first, then by name.
        Non-numeric strings match by name (case-insensitive).
        Raises ``TaskNotFoundError`` when no task matches.
        """
        s = str(selector).strip()
        if s.isdigit():
            task_id = int(s)
            for t in tasks:
                if t.id == task_id:
                    return t
        search = s.casefold()
        for t in tasks:
            if t.name.casefold() == search:
                return t
        available = ", ".join(f"{t.name!r} (id={t.id})" for t in tasks)
        raise TaskNotFoundError(f"Task not found: {s!r}. Available tasks: {available}")

    @staticmethod
    def resolve_task_selectors(
        tasks: list[TaskInfo],
        selectors: Sequence[int | str],
    ) -> list[TaskInfo]:
        """Resolve a list of task selectors to matching tasks.

        Each selector is resolved independently via
        ``_resolve_one_task_selector``.  Duplicates (same task matched
        by different selectors) are removed, preserving order.
        """
        seen_ids: set[int] = set()
        matched: list[TaskInfo] = []
        for sel in selectors:
            task = CvatClient._resolve_one_task_selector(tasks, sel)
            if task.id not in seen_ids:
                seen_ids.add(task.id)
                matched.append(task)
        return matched

    @staticmethod
    def _prepare_fetch(
        api: CvatApiPort,
        project_id: int,
        options: _FetchAnnotationsOptions,
    ) -> FetchContext:
        """Get task list and labels, apply filters, return context."""
        tasks = api.get_project_tasks(project_id)
        labels = api.get_project_labels(project_id)
        label_names, attr_names = _build_label_maps(labels)
        tasks = _filter_tasks_for_fetch(tasks, options)
        return FetchContext(
            tasks=tasks,
            label_names=label_names,
            attr_names=attr_names,
            host=options.host,
            project_name=options.project_name,
        )

    @staticmethod
    def _fetch_one_task(
        api: CvatApiPort,
        task: TaskInfo,
        ctx: FetchContext,
    ) -> TaskAnnotations | None:
        """Fetch annotations for a single task via the API port.

        Returns ``None`` when the task was skipped (5xx with
        ``CVETA2_RAISE_ON_FAILURE`` not set).
        """
        raise_on_failure = (
            os.environ.get("CVETA2_RAISE_ON_FAILURE", "").lower() == "true"
        )
        try:
            data_meta = api.get_task_data_meta(task.id)
            annotations = api.get_task_annotations(task.id)
        except ApiException as e:
            status = getattr(e, "status", 0)
            if _HTTP_5XX_MIN <= status < _HTTP_5XX_MAX:
                if raise_on_failure:
                    raise
                _log_task_5xx_skip(task, ctx.host, ctx.project_name, status, e)
                return None
            raise

        records, deleted = _task_to_records(
            task, data_meta, annotations, ctx.label_names, ctx.attr_names
        )
        return TaskAnnotations(
            task_id=task.id,
            task_name=task.name,
            annotations=records,
            deleted_images=deleted,
        )

    @staticmethod
    def _fetch_annotations(
        api: CvatApiPort,
        project_id: int,
        options: _FetchAnnotationsOptions,
    ) -> ProjectAnnotations:
        """Fetch annotations through a ``CvatApiPort`` implementation."""
        ctx = CvatClient._prepare_fetch(api, project_id, options)
        if not ctx.tasks:
            logger.warning("No tasks in this project.")
            return ProjectAnnotations(
                annotations=[],
                deleted_images=[],
            )

        task_results: list[TaskAnnotations] = []
        for task in tqdm(ctx.tasks, desc="Processing tasks", unit="task", leave=False):
            result = CvatClient._fetch_one_task(api, task, ctx)
            if result is not None:
                task_results.append(result)

        merged = TaskAnnotations.merge(task_results)
        bbox_count = sum(1 for r in merged.annotations if isinstance(r, BBoxAnnotation))
        without_count = len(merged.annotations) - bbox_count
        logger.trace(
            f"Fetched {bbox_count} bbox annotation(s), "
            f"{len(merged.deleted_images)} deleted image(s), "
            f"{without_count} image(s) without annotations",
        )
        return merged

    # ------------------------------------------------------------------
    # Image download
    # ------------------------------------------------------------------

    def download_images(
        self,
        annotations: ProjectAnnotations,
        target_dir: Path,
        project_id: int | None = None,
        project_cloud_storage: CloudStorageInfo | None = None,
    ) -> DownloadStats:
        """Download project images from S3 cloud storage into *target_dir*.

        Requires an active context manager (``with CvatClient(...) as c:``).
        Uses the raw SDK client to detect cloud storage and boto3 for S3.
        Images are saved directly as ``target_dir / image_name`` — no
        additional subdirectories are created.  Already-cached files are
        skipped.

        Images are always downloaded from the **project** cloud storage
        (project's ``source_storage`` via :meth:`detect_project_cloud_storage`
        when *project_id* is given). Per-task storage is not used. If
        *project_id* is not given, project storage cannot be resolved and
        all images will be reported as failed.
        """
        if project_cloud_storage is None and project_id is not None:
            project_cloud_storage = self.detect_project_cloud_storage(project_id)
        downloader = ImageDownloader(target_dir)
        return downloader.download(
            annotations, project_cloud_storage=project_cloud_storage
        )

    # ------------------------------------------------------------------
    # S3 sync
    # ------------------------------------------------------------------

    def detect_project_cloud_storage(
        self,
        project_id: int,
    ) -> CloudStorageInfo | None:
        """Detect cloud storage for a project from the project's source_storage.

        Returns the :class:`CloudStorageInfo` from the project's own
        ``source_storage.cloud_storage_id`` (ProjectRead API), or ``None``
        if the project has no source_storage.

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        sdk = self._require_sdk("detect_project_cloud_storage")
        project = sdk.projects.retrieve(project_id)
        source_storage = getattr(project, "source_storage", None)
        if source_storage is None:
            return None
        if isinstance(source_storage, dict):
            cs_id: int | None = source_storage.get("cloud_storage_id")
        else:
            cs_id = getattr(source_storage, "cloud_storage_id", None)
        if cs_id is None:
            return None
        cs_api = sdk.api_client.cloudstorages_api
        cs_raw, _ = cs_api.retrieve(cs_id)
        return parse_cloud_storage(cs_raw)

    def sync_project_images(
        self,
        project_id: int,
        target_dir: Path,
        project_cloud_storage: CloudStorageInfo | None = None,
    ) -> DownloadStats:
        """Sync all S3 objects for *project_id* into *target_dir*.

        Lists every object under the project's cloud storage prefix and
        downloads those missing locally.  Never deletes from S3 or syncs
        in reverse.

        When *project_cloud_storage* is provided, uses it; otherwise
        calls :meth:`detect_project_cloud_storage`(project_id).

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        if project_cloud_storage is None:
            project_cloud_storage = self.detect_project_cloud_storage(project_id)
        cs_info = project_cloud_storage
        if cs_info is None:
            logger.warning(
                f"Проект {project_id}: cloud storage не найден — "
                f"пропускаем синхронизацию."
            )
            return DownloadStats(total=0)

        logger.info(
            f"Проект {project_id}: синхронизация из "
            f"s3://{cs_info.bucket}/{cs_info.prefix} → {target_dir}"
        )
        syncer = S3Syncer(target_dir)
        return syncer.sync(cs_info)

    # ------------------------------------------------------------------
    # Task creation
    # ------------------------------------------------------------------

    def create_upload_task(
        self,
        project_id: int,
        name: str,
        image_names: list[str],
        cloud_storage_id: int,
        segment_size: int = 100,
    ) -> int:
        """Create a CVAT task backed by cloud storage images.

        Creates one task with ``segment_size`` controlling how many images
        go into each job (CVAT splits automatically).  After attaching data
        the method **waits** for CVAT to finish processing the cloud storage
        files (up to ``_DATA_PROCESSING_TIMEOUT`` seconds) so that subsequent
        annotation uploads land on the correct frames.

        Parameters
        ----------
        project_id:
            CVAT project to attach the task to.
        name:
            Human-readable task name.
        image_names:
            File names inside the cloud storage to include in the task.
        cloud_storage_id:
            CVAT cloud storage ID to read images from.
        segment_size:
            Maximum frames per job (CVAT auto-creates multiple jobs).

        Returns
        -------
        int
            The newly created task ID.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        import time  # noqa: PLC0415

        sdk = self._require_sdk("create_upload_task")

        from cvat_sdk.api_client import models as cvat_models  # noqa: PLC0415

        task_spec = cvat_models.TaskWriteRequest(
            name=name,
            project_id=project_id,
            segment_size=segment_size,
        )
        task, _ = sdk.api_client.tasks_api.create(task_spec)
        logger.info(f"Создана задача: {task.name} (id={task.id})")

        data_request = cvat_models.DataRequest(
            image_quality=70,
            server_files=image_names,
            cloud_storage_id=cloud_storage_id,
            use_cache=True,
            sorting_method=cvat_models.SortingMethod("natural"),
        )
        sdk.api_client.tasks_api.create_data(
            task.id,
            data_request=data_request,
        )

        # Wait for CVAT to finish processing cloud storage data.
        # Without this, annotation uploads arrive before frames are indexed
        # and are silently discarded.
        task_obj = None
        for _ in range(_DATA_PROCESSING_TIMEOUT):
            time.sleep(1)
            task_obj = sdk.tasks.retrieve(int(task.id))
            if task_obj.size and task_obj.size > 0:
                break
        else:
            logger.warning(
                f"Задача {task.id}: обработка данных не завершилась "
                f"за {_DATA_PROCESSING_TIMEOUT}с — аннотации могут быть потеряны"
            )

        size_info = f", size={task_obj.size}" if task_obj else ""
        logger.info(
            f"Привязано {len(image_names)} изображений к задаче {task.id} "
            f"(cloud_storage_id={cloud_storage_id}, "
            f"segment_size={segment_size}{size_info})"
        )
        return int(task.id)

    def upload_task_annotations(
        self,
        task_id: int,
        annotations_df: pd.DataFrame,
    ) -> int:
        """Upload bbox annotations from a DataFrame to an existing task.

        Frame indices are read from CVAT ``data_meta`` so the mapping is
        always correct regardless of how CVAT sorted the images.

        Parameters
        ----------
        task_id:
            CVAT task to upload annotations to.
        annotations_df:
            DataFrame with columns from ``dataset.csv`` (must include
            ``image_name``, ``instance_label``, ``bbox_x_tl``,
            ``bbox_y_tl``, ``bbox_x_br``, ``bbox_y_br``).
            Rows with NaN in ``instance_label`` are skipped.

        Returns
        -------
        int
            Number of shapes uploaded.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        sdk = self._require_sdk("upload_task_annotations")

        from cvat_sdk.api_client import models as cvat_models  # noqa: PLC0415
        from cvat_sdk.core.proxies.annotations import (  # noqa: PLC0415
            AnnotationUpdateAction,
        )

        # Read actual frame mapping from CVAT (authoritative source).
        # Frame index = position in the data_meta.frames list.
        data_meta, _ = sdk.api_client.tasks_api.retrieve_data_meta(task_id)
        name_to_frame: dict[str, int] = {
            frame.name: idx for idx, frame in enumerate(data_meta.frames)
        }

        logger.debug(f"Задача {task_id}: получено {len(name_to_frame)} фреймов из CVAT")

        # Get label name -> label_id mapping from the task
        task_obj = sdk.tasks.retrieve(task_id)
        task_labels = task_obj.get_labels()
        label_name_to_id: dict[str, int] = {lbl.name: lbl.id for lbl in task_labels}

        # Filter to rows with actual annotations (non-NaN label + bbox)
        bbox_cols = ["bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"]
        has_annotation = annotations_df["instance_label"].notna() & annotations_df[
            bbox_cols
        ].notna().all(axis=1)
        ann_rows = annotations_df[has_annotation]

        shapes: list[cvat_models.LabeledShapeRequest] = []
        skipped = 0
        for _, row in ann_rows.iterrows():
            img_name = str(row["image_name"])
            label_name = str(row["instance_label"])
            if img_name not in name_to_frame:
                skipped += 1
                continue
            if label_name not in label_name_to_id:
                logger.warning(
                    f"Метка {label_name!r} не найдена в задаче {task_id} — пропускаем"
                )
                continue
            shapes.append(
                cvat_models.LabeledShapeRequest(
                    type=cvat_models.ShapeType("rectangle"),
                    frame=name_to_frame[img_name],
                    label_id=label_name_to_id[label_name],
                    points=[
                        float(row["bbox_x_tl"]),
                        float(row["bbox_y_tl"]),
                        float(row["bbox_x_br"]),
                        float(row["bbox_y_br"]),
                    ],
                ),
            )

        if skipped:
            logger.warning(
                f"{skipped} аннотаций пропущено: изображение не найдено в задаче"
            )

        if shapes:
            task_obj.update_annotations(
                cvat_models.PatchedLabeledDataRequest(shapes=shapes),
                action=AnnotationUpdateAction.CREATE,
            )
            logger.info(f"Загружено {len(shapes)} аннотаций в задачу {task_id}")
        else:
            logger.info(f"Нет аннотаций для загрузки в задачу {task_id}")

        return len(shapes)

    def mark_frames_deleted(
        self,
        task_id: int,
        image_names: set[str],
    ) -> int:
        """Mark frames as deleted in an existing CVAT task.

        Reads ``data_meta`` to map image names to frame indices, then
        updates the task's ``deleted_frames`` list via
        ``partial_update_data_meta``.

        Parameters
        ----------
        task_id:
            CVAT task ID.
        image_names:
            Image file names to mark as deleted.

        Returns
        -------
        int
            Number of frames actually marked as deleted.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        sdk = self._require_sdk("mark_frames_deleted")

        from cvat_sdk.api_client import models as cvat_models  # noqa: PLC0415

        data_meta, _ = sdk.api_client.tasks_api.retrieve_data_meta(task_id)
        name_to_frame: dict[str, int] = {
            frame.name: idx for idx, frame in enumerate(data_meta.frames)
        }
        frame_ids = sorted(name_to_frame[n] for n in image_names if n in name_to_frame)
        if not frame_ids:
            return 0

        current_deleted = set(data_meta.deleted_frames or [])
        new_deleted = sorted(current_deleted | set(frame_ids))
        sdk.api_client.tasks_api.partial_update_data_meta(
            task_id,
            patched_data_meta_write_request=cvat_models.PatchedDataMetaWriteRequest(
                deleted_frames=new_deleted,
            ),
        )
        logger.info(f"Помечено удалёнными {len(frame_ids)} кадров в задаче {task_id}")
        return len(frame_ids)

    def complete_task(self, task_id: int) -> int:
        """Mark all jobs of a task as completed.

        Sets each job's ``stage`` to ``acceptance`` and ``state`` to
        ``completed``.  CVAT derives the task status from its jobs, so
        once every job is completed the task status becomes ``completed``.

        Parameters
        ----------
        task_id:
            CVAT task ID.

        Returns
        -------
        int
            Number of jobs updated.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        sdk = self._require_sdk("complete_task")

        from cvat_sdk.api_client import models as cvat_models  # noqa: PLC0415

        task_obj = sdk.tasks.retrieve(task_id)
        jobs = task_obj.get_jobs()
        jobs_api = sdk.api_client.jobs_api
        for job in jobs:
            jobs_api.partial_update(
                job.id,
                patched_job_write_request=cvat_models.PatchedJobWriteRequest(
                    stage=cvat_models.JobStage("acceptance"),
                    state=cvat_models.OperationStatus("completed"),
                ),
            )
        logger.info(f"Задача {task_id} завершена ({len(jobs)} job(s) → completed)")
        return len(jobs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_sdk(self, method_name: str) -> Any:  # noqa: ANN401
        """Return the raw SDK client or raise with a helpful message."""
        if self._sdk_client is None:
            msg = (
                f"{method_name}() requires a context manager. "
                "Use: with CvatClient(cfg) as client: ..."
            )
            raise RuntimeError(msg)
        sdk = self._persistent_api.client if self._persistent_api else None
        if sdk is None:
            msg = "SDK client not available."
            raise RuntimeError(msg)
        return sdk

    def _build_client_kwargs(self, cfg: CvatConfig) -> dict[str, Any]:
        """Build keyword arguments for ``make_client``.

        ``organization`` is not passed to ``make_client`` (SDK does not
        accept it).  It is set on the client instance afterwards.
        """
        kwargs: dict[str, Any] = {"host": cfg.host}
        if cfg.username and cfg.password:
            kwargs["credentials"] = (cfg.username, cfg.password)
        return kwargs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _project_annotations_to_csv_rows(
    result: ProjectAnnotations,
) -> list[dict[str, str | int | float | bool | None]]:
    """Build CSV rows — thin wrapper around ``ProjectAnnotations.to_csv_rows``.

    .. deprecated::
        Use ``result.to_csv_rows()`` directly instead.
    """
    return result.to_csv_rows()


def fetch_annotations(
    project_id: int,
    cfg: CvatConfig | None = None,
    *,
    completed_only: bool = False,
    ignore_task_ids: set[int] | None = None,
    task_selector: list[int | str] | None = None,
) -> pd.DataFrame:
    """Fetch project annotations as a pandas DataFrame.

    Includes one row per bbox annotation and one row per image that has no
    annotations (missing bbox/annotation fields filled with None).
    For full structured output (including deleted images), use ``CvatClient``.
    """
    resolved_cfg = cfg or CvatConfig.load()
    result = CvatClient(resolved_cfg).fetch_annotations(
        project_id,
        completed_only=completed_only,
        ignore_task_ids=ignore_task_ids,
        task_selector=task_selector,
    )
    rows = result.to_csv_rows()
    if not rows:
        return pd.DataFrame(columns=list(CSV_COLUMNS))
    return pd.DataFrame(rows)

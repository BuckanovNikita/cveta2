"""CVAT client logic: connect, fetch annotations, extract shapes."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Protocol

import pandas as pd
from cvat_sdk import make_client
from loguru import logger
from tqdm import tqdm

from cveta2._client.context import _TaskContext
from cveta2._client.extractors import _collect_shapes
from cveta2._client.mapping import _build_label_maps
from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.config import CvatConfig
from cveta2.exceptions import ProjectNotFoundError, TaskNotFoundError
from cveta2.image_downloader import DownloadStats, ImageDownloader, S3Syncer
from cveta2.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
)
from cveta2.projects_cache import ProjectInfo

_DATA_PROCESSING_TIMEOUT = int(os.environ.get("CVETA2_DATA_TIMEOUT", "60"))
"""Max seconds to wait for CVAT to finish processing cloud storage data.

Configurable via ``CVETA2_DATA_TIMEOUT`` env var (default 60).
"""

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager
    from pathlib import Path
    from types import TracebackType

    from typing_extensions import Self

    from cveta2._client.dtos import RawTask
    from cveta2._client.ports import CvatApiPort
    from cveta2.image_downloader import CloudStorageInfo


class _SdkClientFactory(Protocol):
    """Protocol for the SDK client factory (e.g. ``cvat_sdk.make_client``).

    The factory must accept keyword arguments (``host``, optionally
    ``access_token`` or ``credentials``) and return a context manager
    that yields an SDK client.
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
        cfg: CvatConfig,
        client_factory: _SdkClientFactory | None = None,
        *,
        api: CvatApiPort | None = None,
    ) -> None:
        """Store client configuration and optional API port for DI.

        When *api* is provided it is used directly.  Otherwise an
        ``SdkCvatApiAdapter`` is created on the fly from an SDK client
        opened via *client_factory*.
        """
        self._cfg = cfg
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_projects(self) -> list[ProjectInfo]:
        """Fetch list of projects from CVAT (id and name)."""
        api = self._get_api()
        if api is not None:
            raw = api.list_projects()
            return [ProjectInfo(id=p.id, name=p.name) for p in raw]
        with self._open_sdk_adapter() as adapter:
            raw = adapter.list_projects()
            return [ProjectInfo(id=p.id, name=p.name) for p in raw]

    def list_project_tasks(self, project_id: int) -> list[RawTask]:
        """Fetch the list of tasks for a project from CVAT."""
        api = self._get_api()
        if api is not None:
            return api.get_project_tasks(project_id)
        with self._open_sdk_adapter() as adapter:
            return adapter.get_project_tasks(project_id)

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
    ) -> ProjectAnnotations:
        """Fetch all bbox annotations and deleted images from a project.

        If ``completed_only`` is True, only completed tasks are processed.
        Tasks whose IDs are in ``ignore_task_ids`` are silently skipped.
        If ``task_selector`` is given (list of task IDs or names), only
        matching tasks are processed.
        """
        api = self._get_api()
        if api is not None:
            return self._fetch_annotations(
                api,
                project_id,
                completed_only=completed_only,
                ignore_task_ids=ignore_task_ids,
                task_selector=task_selector,
            )
        with self._open_sdk_adapter() as adapter:
            return self._fetch_annotations(
                adapter,
                project_id,
                completed_only=completed_only,
                ignore_task_ids=ignore_task_ids,
                task_selector=task_selector,
            )

    # ------------------------------------------------------------------
    # Core annotation logic (single code path for all API backends)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_one_task_selector(
        tasks: list[RawTask],
        selector: int | str,
    ) -> RawTask:
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
    def _resolve_task_selectors(
        tasks: list[RawTask],
        selectors: list[int | str],
    ) -> list[RawTask]:
        """Resolve a list of task selectors to matching tasks.

        Each selector is resolved independently via
        ``_resolve_one_task_selector``.  Duplicates (same task matched
        by different selectors) are removed, preserving order.
        """
        seen_ids: set[int] = set()
        matched: list[RawTask] = []
        for sel in selectors:
            task = CvatClient._resolve_one_task_selector(tasks, sel)
            if task.id not in seen_ids:
                seen_ids.add(task.id)
                matched.append(task)
        return matched

    @staticmethod
    def _fetch_annotations(
        api: CvatApiPort,
        project_id: int,
        *,
        completed_only: bool = False,
        ignore_task_ids: set[int] | None = None,
        task_selector: list[int | str] | None = None,
    ) -> ProjectAnnotations:
        """Fetch annotations through a ``CvatApiPort`` implementation."""
        tasks = api.get_project_tasks(project_id)
        labels = api.get_project_labels(project_id)
        label_names, attr_names = _build_label_maps(labels)

        if ignore_task_ids:
            skipped = [t for t in tasks if t.id in ignore_task_ids]
            if skipped:
                logger.warning(f"Пропускаем {len(skipped)} задач(а) из ignore-списка:")
                for t in skipped:
                    logger.warning(
                        f"  - #{t.id} {t.name!r} (обновлена: {t.updated_date})"
                    )
            tasks = [t for t in tasks if t.id not in ignore_task_ids]

        if task_selector is not None:
            tasks = CvatClient._resolve_task_selectors(tasks, task_selector)
            names = ", ".join(f"{t.name!r} (id={t.id})" for t in tasks)
            logger.info(f"Selected {len(tasks)} task(s): {names}")

        if completed_only:
            tasks = [t for t in tasks if t.status == "completed"]
            logger.trace(f"Filtered to {len(tasks)} completed task(s)")
        if not tasks:
            logger.warning("No tasks in this project.")
            return ProjectAnnotations(
                annotations=[],
                deleted_images=[],
            )

        all_annotations: list[BBoxAnnotation] = []
        all_deleted: list[DeletedImage] = []
        all_without: list[ImageWithoutAnnotations] = []

        for task in tqdm(tasks, desc="Processing tasks", unit="task", leave=False):
            data_meta = api.get_task_data_meta(task.id)
            annotations = api.get_task_annotations(task.id)

            # NOTE: Only direct shapes are processed. Track-based annotations
            # (interpolated/linked bboxes) are intentionally skipped — cveta2
            # targets per-frame bbox exports, not temporal tracking data.
            if annotations.tracks:
                logger.warning(
                    f"Task {task.name!r} has {len(annotations.tracks)} track(s) "
                    f"that will be skipped (only direct shapes are extracted)"
                )

            ctx = _TaskContext.from_raw(
                task,
                data_meta,
                label_names,
                attr_names,
            )
            task_annotations = _collect_shapes(
                annotations.shapes,
                ctx,
            )

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

            all_annotations.extend(task_annotations)
            all_deleted.extend(task_deleted)
            all_without.extend(task_without)

        logger.trace(
            f"Fetched {len(all_annotations)} bbox annotation(s), "
            f"{len(all_deleted)} deleted image(s), "
            f"{len(all_without)} image(s) without annotations",
        )
        return ProjectAnnotations(
            annotations=all_annotations,
            deleted_images=all_deleted,
            images_without_annotations=all_without,
        )

    # ------------------------------------------------------------------
    # Image download
    # ------------------------------------------------------------------

    def download_images(
        self,
        annotations: ProjectAnnotations,
        target_dir: Path,
    ) -> DownloadStats:
        """Download project images from S3 cloud storage into *target_dir*.

        Requires an active context manager (``with CvatClient(...) as c:``).
        Uses the raw SDK client to detect cloud storage and boto3 for S3.
        Images are saved directly as ``target_dir / image_name`` — no
        additional subdirectories are created.  Already-cached files are
        skipped.
        """
        sdk = self._require_sdk("download_images")
        downloader = ImageDownloader(target_dir)
        return downloader.download(sdk, annotations)

    # ------------------------------------------------------------------
    # S3 sync
    # ------------------------------------------------------------------

    def detect_project_cloud_storage(
        self,
        project_id: int,
    ) -> CloudStorageInfo | None:
        """Detect cloud storage for a project by probing its tasks.

        Returns the :class:`CloudStorageInfo` from the first task that has
        a ``source_storage`` with a ``cloud_storage_id``, or ``None`` if
        no task has one.

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        sdk = self._require_sdk("detect_project_cloud_storage")
        api = self._get_api()
        if api is None:
            msg = "API port not available."
            raise RuntimeError(msg)

        tasks = api.get_project_tasks(project_id)
        cs_cache: dict[int, CloudStorageInfo] = {}
        for task in tasks:
            cs_info = ImageDownloader.detect_cloud_storage(sdk, task.id, cs_cache)
            if cs_info is not None:
                return cs_info
        return None

    def sync_project_images(
        self,
        project_id: int,
        target_dir: Path,
    ) -> DownloadStats:
        """Sync all S3 objects for *project_id* into *target_dir*.

        Lists every object under the project's cloud storage prefix and
        downloads those missing locally.  Never deletes from S3 or syncs
        in reverse.

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        cs_info = self.detect_project_cloud_storage(project_id)
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
        if cfg.token:
            kwargs["access_token"] = cfg.token
        elif cfg.username and cfg.password:
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

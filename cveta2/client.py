"""CVAT client logic: connect, fetch annotations, orchestrate task operations.

All CVAT SDK interaction goes through :class:`CvatApiPort`
(``cveta2._client``); this module holds only domain orchestration.
"""

from __future__ import annotations

import os
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger
from tqdm import tqdm

from cveta2._client.assembly import (
    build_name_to_frame,
    find_job_for_frame,
    issue_position_from_row,
    task_to_records,
)
from cveta2._client.connection import open_sdk_api
from cveta2._client.dtos import LabelPatch, NewIssue, NewShape, UploadTaskSpec
from cveta2._client.mapping import _build_label_maps
from cveta2.config import CvatConfig
from cveta2.exceptions import CvatApiError, ProjectNotFoundError, TaskNotFoundError
from cveta2.image_downloader import (
    CloudStorageInfo,
    DownloadStats,
    ImageDownloader,
    S3Syncer,
)
from cveta2.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    LabelInfo,
    ProjectAnnotations,
    ProjectInfo,
    TaskAnnotations,
    TaskInfo,
)

_HTTP_5XX_MIN = 500
_HTTP_5XX_MAX = 600

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path
    from types import TracebackType

    from typing_extensions import Self

    from cveta2._client.connection import SdkClientFactory
    from cveta2._client.dtos import RawDataMeta, RawShape
    from cveta2._client.ports import CvatApiPort


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
    e: CvatApiError,
) -> None:
    """Log 5xx error and ignore-command hint for a skipped task."""
    task_link = (
        f"{host.rstrip('/')}/tasks/{task.id}"
        if host
        else f"task_id={task.id} {task.name!r}"
    )
    logger.error(f"CVAT server error (HTTP {e.status_code}) for task {task_link}: {e}")
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


def _select_new_issue_rows(annotations_df: pd.DataFrame) -> pd.DataFrame:
    """Return deduplicated rows with ``issue_state == "new"`` and non-empty text."""
    if "issue_state" not in annotations_df.columns:
        return pd.DataFrame()
    df = annotations_df.copy()
    if "issue_text" not in df.columns:
        df["issue_text"] = ""
    df["issue_state"] = df["issue_state"].fillna("").astype(str).str.strip()
    df["issue_text"] = df["issue_text"].fillna("").astype(str).str.strip()
    new_rows: pd.DataFrame = df[(df["issue_state"] == "new") & (df["issue_text"] != "")]
    deduped: pd.DataFrame = new_rows.drop_duplicates(
        subset=["image_name", "issue_text"]
    )
    return deduped


class CvatClient:
    """High-level CVAT client that fetches bbox annotations.

    Can be used as a context manager to keep the SDK connection open
    across multiple calls::

        with CvatClient(cfg) as client:
            projects = client.list_projects()
            result = client.fetch_annotations(project_id)

    Without the context manager, read methods open and close their own
    connection per call; write methods require the context manager (or
    an injected ``api``).
    """

    def __init__(
        self,
        cfg: CvatConfig | None = None,
        client_factory: SdkClientFactory | None = None,
        *,
        api: CvatApiPort | None = None,
    ) -> None:
        """Store client configuration and optional API port for DI.

        When *cfg* is ``None``, configuration is loaded automatically
        from environment variables, config file, and built-in preset
        via :meth:`CvatConfig.load`.

        When *api* is provided it is used directly (no connection is
        opened).  Otherwise an SDK-backed adapter is opened via
        *client_factory*.
        """
        self._cfg = cfg or CvatConfig.load()
        self._client_factory = client_factory
        self._api = api
        # Persistent API opened by __enter__, closed by __exit__.
        self._persistent_api: CvatApiPort | None = None
        self._exit_stack: ExitStack | None = None

    # ------------------------------------------------------------------
    # Context manager (optional connection reuse)
    # ------------------------------------------------------------------

    def __enter__(self) -> Self:
        """Open a persistent SDK connection for the lifetime of this block."""
        if self._api is not None:
            # DI api provided -- nothing to open.
            return self
        resolved = self._cfg.ensure_credentials()
        self._exit_stack = ExitStack()
        self._persistent_api = self._exit_stack.enter_context(
            open_sdk_api(resolved, self._client_factory)
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the persistent SDK connection."""
        self._persistent_api = None
        if self._exit_stack is not None:
            stack, self._exit_stack = self._exit_stack, None
            stack.__exit__(exc_type, exc_val, exc_tb)

    # ------------------------------------------------------------------
    # API port lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def open_api(self) -> Iterator[CvatApiPort]:
        """Context manager yielding the best available API port.

        Uses injected or persistent API if available, otherwise opens
        a fresh SDK adapter.
        """
        api = self._api or self._persistent_api
        if api is not None:
            yield api
        else:
            resolved = self._cfg.ensure_credentials()
            with open_sdk_api(resolved, self._client_factory) as adapter:
                yield adapter

    def _require_api(self, method_name: str) -> CvatApiPort:
        """Return the injected or persistent API port, or raise."""
        api = self._api or self._persistent_api
        if api is None:
            msg = (
                f"{method_name}() requires a context manager. "
                "Use: with CvatClient(cfg) as client: ..."
            )
            raise RuntimeError(msg)
        return api

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_projects(self) -> list[ProjectInfo]:
        """Fetch list of projects from CVAT (id and name)."""
        with self.open_api() as source:
            return source.list_projects()

    def list_project_tasks(self, project_id: int) -> list[TaskInfo]:
        """Fetch the list of tasks for a project from CVAT."""
        with self.open_api() as source:
            return source.get_project_tasks(project_id)

    def list_tasks_completed_after(
        self,
        project_id: int,
        cutoff: str,
    ) -> list[TaskInfo]:
        """List completed project tasks updated strictly after *cutoff*.

        *cutoff* and task ``updated_date`` values are normalized ISO
        strings (see ``_extract_updated_date`` in the SDK adapter), so
        lexicographic comparison matches chronological order.  Tasks
        without an ``updated_date`` are treated as not-newer.  The result
        is sorted by ``updated_date`` ascending.
        """
        tasks = self.list_project_tasks(project_id)
        newer = [
            t
            for t in tasks
            if t.status == "completed" and t.updated_date and t.updated_date > cutoff
        ]
        return sorted(newer, key=lambda t: t.updated_date)

    def get_project_labels(self, project_id: int) -> list[LabelInfo]:
        """Fetch label definitions for a project from CVAT."""
        with self.open_api() as source:
            return source.get_project_labels(project_id)

    def count_label_usage(self, project_id: int) -> dict[int, int]:
        """Count annotations per label across all project tasks.

        Returns a mapping ``{label_id: annotation_count}``.
        Used to warn before label deletion.
        """
        with self.open_api() as source:
            tasks = source.get_project_tasks(project_id)
            counts: dict[int, int] = {}
            skipped: list[int] = []
            for task in tqdm(
                tasks, desc="Checking annotations", unit="task", leave=False
            ):
                try:
                    annotations = source.get_task_annotations(task.id)
                except CvatApiError:
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
        api = self._require_api("update_project_labels")

        patches: list[LabelPatch] = [LabelPatch(name=name) for name in (add or [])]
        patches.extend(
            LabelPatch(id=lid, name=new_name)
            for lid, new_name in (rename or {}).items()
        )
        patches.extend(LabelPatch(id=lid, deleted=True) for lid in (delete or []))
        patches.extend(
            LabelPatch(id=lid, color=color) for lid, color in (recolor or {}).items()
        )
        if not patches:
            return
        api.patch_project_labels(project_id, patches)

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

    def fetch_annotations(  # noqa: PLR0913
        self,
        project_id: int,
        *,
        completed_only: bool = False,
        ignore_task_ids: set[int] | None = None,
        silent_task_ids: set[int] | None = None,
        task_selector: list[int | str] | None = None,
        project_name: str = "",
    ) -> ProjectAnnotations:
        """Fetch all bbox annotations and deleted images from a project.

        If ``completed_only`` is True, only completed tasks are processed.
        Tasks whose IDs are in ``ignore_task_ids`` are silently skipped.
        ``silent_task_ids`` suppresses the skip-warning for those IDs.
        If ``task_selector`` is given (list of task IDs or names), only
        matching tasks are processed.
        """
        options = _FetchAnnotationsOptions(
            completed_only=completed_only,
            ignore_task_ids=ignore_task_ids,
            silent_task_ids=silent_task_ids,
            task_selector=task_selector,
            host=(self._cfg.host or ""),
            project_name=project_name,
        )
        with self.open_api() as source:
            return self._fetch_annotations(source, project_id, options)

    def prepare_fetch(  # noqa: PLR0913
        self,
        project_id: int,
        *,
        completed_only: bool = False,
        ignore_task_ids: set[int] | None = None,
        silent_task_ids: set[int] | None = None,
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
            silent_task_ids=silent_task_ids,
            task_selector=task_selector,
            host=(self._cfg.host or ""),
            project_name=project_name,
        )
        with self.open_api() as source:
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
    def fetch_one_task(
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
        except CvatApiError as e:
            if _HTTP_5XX_MIN <= e.status_code < _HTTP_5XX_MAX:
                if raise_on_failure:
                    raise
                _log_task_5xx_skip(task, ctx.host, ctx.project_name, e)
                return None
            raise

        try:
            issues = api.get_task_issues(task.id)
        except CvatApiError as e:
            logger.warning(
                f"Не удалось получить issues задачи {task.id}: {e} — "
                f"колонки issue_text/issue_state останутся пустыми"
            )
            issues = []

        records, deleted = task_to_records(
            task, data_meta, annotations, ctx.label_names, ctx.attr_names, issues
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
            result = CvatClient.fetch_one_task(api, task, ctx)
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
        api = self._require_api("detect_project_cloud_storage")
        return api.get_project_cloud_storage(project_id)

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

    def create_upload_task(  # noqa: PLR0913
        self,
        project_id: int,
        name: str,
        image_names: list[str],
        cloud_storage_id: int,
        segment_size: int = 100,
        image_quality: int = 100,
    ) -> int:
        """Create a CVAT task backed by cloud storage images.

        Creates one task with ``segment_size`` controlling how many images
        go into each job (CVAT splits automatically).  After attaching data
        the method **waits** for CVAT to finish processing the cloud storage
        files so that subsequent annotation uploads land on the correct
        frames.  Raises ``RuntimeError`` immediately if processing fails
        (e.g. images not found in cloud storage).

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
        image_quality:
            JPEG compression quality for CVAT image chunks (0-100).

        Returns
        -------
        int
            The newly created task ID.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        api = self._require_api("create_upload_task")
        spec = UploadTaskSpec(
            project_id=project_id,
            name=name,
            server_files=image_names,
            cloud_storage_id=cloud_storage_id,
            segment_size=segment_size,
            image_quality=image_quality,
        )
        return api.create_task_with_data(spec)

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
        api = self._require_api("upload_task_annotations")

        # Read actual frame mapping from CVAT (authoritative source).
        raw_meta = api.get_task_data_meta(task_id)
        name_to_frame = build_name_to_frame(raw_meta)

        logger.debug(f"Задача {task_id}: получено {len(name_to_frame)} фреймов из CVAT")

        task_labels = api.get_task_labels(task_id)
        label_name_to_id: dict[str, int] = {lbl.name: lbl.id for lbl in task_labels}

        # Filter to rows with actual annotations (non-NaN label + bbox)
        bbox_cols = ["bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"]
        has_annotation = annotations_df["instance_label"].notna() & annotations_df[
            bbox_cols
        ].notna().all(axis=1)
        ann_rows = annotations_df[has_annotation]

        shapes: list[NewShape] = []
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
                NewShape(
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
            api.put_task_shapes(task_id, shapes)
            logger.info(f"Загружено {len(shapes)} аннотаций в задачу {task_id}")
        else:
            logger.info(f"Нет аннотаций для загрузки в задачу {task_id}")

        return len(shapes)

    def create_task_issues(
        self,
        task_id: int,
        annotations_df: pd.DataFrame,
    ) -> int:
        """Create open CVAT issues from rows with ``issue_state == "new"``.

        Rows whose ``issue_state`` is ``"new"`` and whose ``issue_text`` is
        non-empty become CVAT issues on *task_id*; ``issue_text`` is posted
        as the first comment.  Duplicate ``(image_name, issue_text)`` pairs
        are created once.  Issues are attached to the row's bbox; rows
        without a complete bbox are skipped with a warning.

        Returns the number of issues created.  Requires an active context
        manager (``with CvatClient(...) as c:``).
        """
        api = self._require_api("create_task_issues")

        new_rows = _select_new_issue_rows(annotations_df)
        if new_rows.empty:
            return 0

        raw_meta = api.get_task_data_meta(task_id)
        name_to_frame = build_name_to_frame(raw_meta)
        jobs = api.get_task_jobs(task_id)

        created = 0
        unknown_images: list[str] = []
        unmapped_frames: list[str] = []
        missing_bbox: list[str] = []
        for _, row in new_rows.iterrows():
            image_name = str(row["image_name"])
            frame = name_to_frame.get(image_name)
            if frame is None:
                unknown_images.append(image_name)
                continue
            position = issue_position_from_row(row)
            if position is None:
                missing_bbox.append(image_name)
                continue
            job_id = find_job_for_frame(jobs, frame)
            if job_id is None:
                unmapped_frames.append(image_name)
                continue
            api.create_issue(
                NewIssue(
                    job_id=job_id,
                    frame=frame,
                    position=position,
                    message=str(row["issue_text"]),
                ),
            )
            created += 1

        if unknown_images:
            logger.warning(
                f"Issues пропущены: изображения не найдены в задаче {task_id}: "
                f"{unknown_images}"
            )
        if missing_bbox:
            logger.warning(
                f"Issues пропущены: у строк нет полного bbox в задаче {task_id}: "
                f"{missing_bbox}"
            )
        if unmapped_frames:
            logger.warning(
                f"Issues пропущены: не найден job для кадров изображений "
                f"в задаче {task_id}: {unmapped_frames}"
            )
        logger.info(f"Создано issues: {created} в задаче {task_id}")
        return created

    def mark_frames_deleted(
        self,
        task_id: int,
        image_names: set[str],
    ) -> int:
        """Mark frames as deleted in an existing CVAT task.

        Reads ``data_meta`` to map image names to frame indices, then
        updates the task's ``deleted_frames`` list.

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
        api = self._require_api("mark_frames_deleted")

        raw_meta = api.get_task_data_meta(task_id)
        name_to_frame = build_name_to_frame(raw_meta)
        frame_ids = sorted(name_to_frame[n] for n in image_names if n in name_to_frame)
        return self._patch_deleted_frames(api, task_id, raw_meta, frame_ids)

    def mark_frames_deleted_by_ids(
        self,
        task_id: int,
        frame_ids: Iterable[int],
    ) -> int:
        """Mark frames as deleted in an existing CVAT task by frame IDs.

        Frame IDs outside the task's frame range are skipped with a
        warning.  The remaining IDs are merged with the current
        ``deleted_frames``.

        Parameters
        ----------
        task_id:
            CVAT task ID.
        frame_ids:
            Frame indices to mark as deleted.

        Returns
        -------
        int
            Number of frames actually marked as deleted.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        api = self._require_api("mark_frames_deleted_by_ids")

        raw_meta = api.get_task_data_meta(task_id)
        num_frames = len(raw_meta.frames)
        requested = sorted(set(frame_ids))
        valid = [fid for fid in requested if 0 <= fid < num_frames]
        unknown = [fid for fid in requested if fid < 0 or fid >= num_frames]
        if unknown:
            logger.warning(
                f"Задача {task_id}: кадры {unknown} не найдены "
                f"(в задаче {num_frames} кадров) — пропускаем"
            )
        return self._patch_deleted_frames(api, task_id, raw_meta, valid)

    @staticmethod
    def _patch_deleted_frames(
        api: CvatApiPort,
        task_id: int,
        raw_meta: RawDataMeta,
        frame_ids: list[int],
    ) -> int:
        """Union *frame_ids* with the task's deleted frames and PATCH data_meta."""
        if not frame_ids:
            return 0
        new_deleted = sorted(set(raw_meta.deleted_frames) | set(frame_ids))
        api.set_deleted_frames(task_id, new_deleted)
        logger.info(f"Помечено удалёнными {len(frame_ids)} кадров в задаче {task_id}")
        return len(frame_ids)

    def count_task_label_shapes(self, task_id: int, label: str) -> int:
        """Count annotation shapes with the given label name in a task.

        Raises ``ValueError`` (listing available labels) when the label
        does not exist in the task.

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        api = self._require_api("count_task_label_shapes")
        return len(self._find_label_shapes(api, task_id, label))

    def drop_label_annotations(self, task_id: int, label: str) -> int:
        """Delete all annotation shapes with the given label from a task.

        Resolves the label name to its ID via the task's labels, collects
        matching shapes and deletes them.

        Parameters
        ----------
        task_id:
            CVAT task ID.
        label:
            Label name whose shapes should be deleted.

        Returns
        -------
        int
            Number of shapes deleted.

        Raises
        ------
        ValueError
            When the label does not exist in the task (message lists
            available labels).

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        api = self._require_api("drop_label_annotations")
        shapes = self._find_label_shapes(api, task_id, label)
        if not shapes:
            logger.info(f"В задаче {task_id} нет аннотаций с меткой {label!r}")
            return 0
        api.delete_shapes(task_id, shapes)
        logger.info(
            f"Удалено {len(shapes)} аннотаций с меткой {label!r} из задачи {task_id}"
        )
        return len(shapes)

    @staticmethod
    def _find_label_shapes(
        api: CvatApiPort,
        task_id: int,
        label: str,
    ) -> list[RawShape]:
        """Return task shapes whose label name equals *label*.

        Raises ``ValueError`` listing available labels when no task label
        matches *label*.
        """
        task_labels = api.get_task_labels(task_id)
        label_ids = {lbl.id for lbl in task_labels if lbl.name == label}
        if not label_ids:
            available = ", ".join(sorted(str(lbl.name) for lbl in task_labels))
            raise ValueError(
                f"Метка {label!r} не найдена в задаче {task_id}. "
                f"Доступные метки: {available}"
            )
        annotations = api.get_task_annotations(task_id)
        return [s for s in annotations.shapes if s.label_id in label_ids]

    def delete_task(self, task_id: int) -> None:
        """Delete a CVAT task permanently (including its data and jobs).

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        api = self._require_api("delete_task")
        api.delete_task(task_id)
        logger.info(f"Задача {task_id} удалена")

    def set_task_jobs_status(
        self,
        task_id: int,
        *,
        stage: str | None = None,
        state: str | None = None,
    ) -> int:
        """Set stage and/or state on every job of a task.

        Only the provided fields are patched.  CVAT derives the task
        status from its jobs.

        Parameters
        ----------
        task_id:
            CVAT task ID.
        stage:
            Job stage: ``annotation``, ``validation`` or ``acceptance``.
        state:
            Job state: ``new``, ``in progress``, ``completed`` or
            ``rejected``.

        Returns
        -------
        int
            Number of jobs updated.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        if stage is None and state is None:
            raise ValueError("Укажите stage и/или state.")
        api = self._require_api("set_task_jobs_status")

        jobs = api.get_task_jobs(task_id)
        for job in jobs:
            api.update_job(job.id, stage=stage, state=state)
        logger.info(
            f"Задача {task_id}: обновлено {len(jobs)} job(s) "
            f"(stage={stage or '-'}, state={state or '-'})"
        )
        return len(jobs)

    def complete_task(self, task_id: int) -> int:
        """Mark all jobs of a task as completed.

        Sets each job's ``stage`` to ``acceptance`` and ``state`` to
        ``completed``.  CVAT derives the task status from its jobs, so
        once every job is completed the task status becomes ``completed``.

        Returns the number of jobs updated.  Requires an active context
        manager (``with CvatClient(...) as c:``).
        """
        return self.set_task_jobs_status(task_id, stage="acceptance", state="completed")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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

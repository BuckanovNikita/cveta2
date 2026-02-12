"""CVAT client logic: connect, fetch annotations, extract shapes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

import pandas as pd
from cvat_sdk import make_client  # type: ignore[import-untyped]
from loguru import logger
from tqdm import tqdm

from cveta2._client.context import _TaskContext
from cveta2._client.extractors import _collect_shapes
from cveta2._client.mapping import _build_label_maps
from cveta2.config import CvatConfig
from cveta2.models import (
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
)
from cveta2.projects_cache import ProjectInfo

if TYPE_CHECKING:
    from collections.abc import Callable

    from cveta2._client.dtos import RawFrame, RawShape


class _TasksApiProtocol(Protocol):
    def retrieve_data_meta(self, task_id: int) -> tuple[object, object]: ...
    def retrieve_annotations(self, task_id: int) -> tuple[object, object]: ...


class _TaskProtocol(Protocol):
    id: int
    name: str
    status: object
    subset: str | None
    updated_date: object | None
    updated_at: object | None


class CvatClient:
    """High-level CVAT client that fetches bbox annotations."""

    def __init__(
        self,
        cfg: CvatConfig,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        """Store client configuration and optional SDK client factory."""
        self._cfg = cfg
        self._client_factory = client_factory or make_client

    def list_projects(self) -> list[ProjectInfo]:
        """Fetch list of projects from CVAT (id and name)."""
        resolved = self._cfg.ensure_credentials()
        client_kwargs = self._build_client_kwargs(resolved)
        with self._client_factory(**client_kwargs) as client:
            if resolved.organization:
                client.organization_slug = resolved.organization
            raw = client.projects.list()
            return [
                ProjectInfo(id=getattr(p, "id", 0), name=getattr(p, "name", "") or "")
                for p in raw
            ]

    def resolve_project_id(
        self,
        project_spec: int | str,
        *,
        cached: list[ProjectInfo] | None = None,
    ) -> int:
        """Resolve project id from numeric id or project name.

        If project_spec is int or digit string, returns it as int.
        If it is a name, looks in cached list first, then in list_projects() from API.
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
        raise ValueError(f"Project not found: {s!r}")

    def fetch_annotations(
        self,
        project_id: int,
        *,
        completed_only: bool = False,
    ) -> ProjectAnnotations:
        """Fetch all bounding-box annotations and deleted images from a CVAT project.

        Returns a ``ProjectAnnotations`` with one ``BBoxAnnotation`` per bounding
        box and a flat list of ``DeletedImage`` records.

        If ``completed_only`` is True, only tasks with status "completed" are processed.
        """
        resolved = self._cfg.ensure_credentials()
        client_kwargs = self._build_client_kwargs(resolved)

        with self._client_factory(**client_kwargs) as client:
            if resolved.organization:
                client.organization_slug = resolved.organization
                logger.trace(f"Using organization: {resolved.organization}")
            project = client.projects.retrieve(project_id)
            logger.trace(f"Project: {project.name} (id={project.id})")
            logger.trace(f"Project structure from API: {project}")

            label_names, attr_names = _build_label_maps(project)

            tasks = project.get_tasks()
            logger.trace(f"Tasks structure from API: {tasks}")
            if completed_only:
                tasks = [t for t in tasks if getattr(t, "status", None) == "completed"]
                logger.trace(f"Filtered to {len(tasks)} completed task(s)")
                logger.trace(f"Completed tasks structure from API: {tasks}")
            if not tasks:
                logger.warning("No tasks in this project.")
                return ProjectAnnotations(annotations=[], deleted_images=[])

            all_annotations: list[BBoxAnnotation] = []
            all_deleted: list[DeletedImage] = []
            all_without_annotations: list[ImageWithoutAnnotations] = []

            for task in tqdm(tasks, desc="Processing tasks", unit="task"):
                task_annotations, task_deleted, task_without_annotations = (
                    self._process_task(
                        tasks_api_obj=client.api_client.tasks_api,
                        task=task,
                        label_names=label_names,
                        attr_names=attr_names,
                    )
                )
                all_annotations.extend(task_annotations)
                all_deleted.extend(task_deleted)
                all_without_annotations.extend(task_without_annotations)

            logger.trace(
                f"Fetched {len(all_annotations)} bbox annotation(s), "
                f"{len(all_deleted)} deleted image(s), "
                f"{len(all_without_annotations)} image(s) without annotations",
            )
            return ProjectAnnotations(
                annotations=all_annotations,
                deleted_images=all_deleted,
                images_without_annotations=all_without_annotations,
            )

    def _process_task(
        self,
        tasks_api_obj: object,
        task: object,
        label_names: dict[int, str],
        attr_names: dict[int, str],
    ) -> tuple[list[BBoxAnnotation], list[DeletedImage], list[ImageWithoutAnnotations]]:
        task_ref = cast("_TaskProtocol", task)
        task_id = task_ref.id
        task_name = task_ref.name
        logger.trace(f"Processing task {task_id} ({task_name})")
        logger.trace(f"Task structure from API: {task}")

        tasks_api = cast("_TasksApiProtocol", tasks_api_obj)
        data_meta, _ = tasks_api.retrieve_data_meta(task_id)
        logger.trace(f"Task data_meta structure from API: {data_meta}")
        frames_raw = cast("list[object] | None", getattr(data_meta, "frames", None))
        frames: dict[int, RawFrame] = cast(
            "dict[int, RawFrame]",
            dict(enumerate(frames_raw or [])),
        )
        logger.trace(f"Task frames structure from API: {frames_raw or []}")
        deleted_frame_ids = (
            cast(
                "list[int] | None",
                getattr(data_meta, "deleted_frames", None),
            )
            or []
        )
        logger.trace(
            f"Task deleted_frames structure from API: {deleted_frame_ids}",
        )

        labeled_data, _ = tasks_api.retrieve_annotations(task_id)
        logger.trace(f"Task annotations structure from API: {labeled_data}")
        shapes: list[RawShape] = cast(
            "list[RawShape]",
            getattr(labeled_data, "shapes", None) or [],
        )

        ctx = _TaskContext(
            frames=frames,
            label_names=label_names,
            attr_names=attr_names,
            task_id=task_id,
            task_name=task_name,
            task_status=str(task_ref.status or ""),
            task_updated_date=self._task_updated_date(task_ref),
            subset=str(task_ref.subset or ""),
        )
        task_annotations = _collect_shapes(shapes, ctx)
        task_deleted = self._collect_deleted_images(
            task=task,
            frames=frames,
            deleted_frame_ids=deleted_frame_ids,
        )
        task_without_annotations = self._collect_without_annotations(
            ctx=ctx,
            frames=frames,
            deleted_frame_ids=set(deleted_frame_ids),
            annotated_frame_ids={a.frame_id for a in task_annotations},
        )
        return task_annotations, task_deleted, task_without_annotations

    def _collect_deleted_images(
        self,
        task: object,
        frames: dict[int, RawFrame],
        deleted_frame_ids: list[int],
    ) -> list[DeletedImage]:
        deleted_images: list[DeletedImage] = []
        task_ref = cast("_TaskProtocol", task)
        for frame_id in deleted_frame_ids:
            frame_info = frames.get(frame_id)
            image_name_raw = getattr(frame_info, "name", None) if frame_info else None
            deleted_images.append(
                DeletedImage(
                    task_id=task_ref.id,
                    task_name=task_ref.name,
                    task_status=str(task_ref.status or ""),
                    task_updated_date=self._task_updated_date(task_ref),
                    frame_id=frame_id,
                    image_name=str(image_name_raw) if image_name_raw else "<unknown>",
                ),
            )
        return deleted_images

    def _collect_without_annotations(
        self,
        ctx: _TaskContext,
        frames: dict[int, RawFrame],
        deleted_frame_ids: set[int],
        annotated_frame_ids: set[int],
    ) -> list[ImageWithoutAnnotations]:
        result: list[ImageWithoutAnnotations] = []
        for frame_id, frame_info in frames.items():
            if frame_id in deleted_frame_ids or frame_id in annotated_frame_ids:
                continue
            name_raw = getattr(frame_info, "name", None)
            width_raw = getattr(frame_info, "width", None)
            height_raw = getattr(frame_info, "height", None)
            if not isinstance(width_raw, (int, float)) or not isinstance(
                height_raw,
                (int, float),
            ):
                logger.trace(f"Skipping frame {frame_id}: missing width/height")
                continue
            result.append(
                ImageWithoutAnnotations(
                    image_name=str(name_raw) if name_raw else "<unknown>",
                    image_width=int(width_raw),
                    image_height=int(height_raw),
                    task_id=ctx.task_id,
                    task_name=ctx.task_name,
                    task_status=ctx.task_status,
                    task_updated_date=ctx.task_updated_date,
                    frame_id=frame_id,
                    subset=ctx.subset,
                ),
            )
        return result

    @staticmethod
    def _task_updated_date(task: _TaskProtocol) -> str:
        task_updated_date_raw: object | None = task.updated_date
        if task_updated_date_raw is None:
            task_updated_date_raw = task.updated_at
        if task_updated_date_raw is None:
            return ""
        isoformat = getattr(task_updated_date_raw, "isoformat", None)
        if callable(isoformat):
            return str(isoformat())
        return str(task_updated_date_raw)

    def _build_client_kwargs(self, cfg: CvatConfig) -> dict[str, Any]:
        """Build keyword arguments for ``make_client`` from a resolved config.

        Note: ``organization`` is not passed to ``make_client`` (SDK does not
        accept it). It is set on the client instance as ``organization_slug``
        after creation so API requests use the organization context.
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
    """Build CSV rows with the same columns as `BBoxAnnotation`."""
    rows = [ann.to_csv_row() for ann in result.annotations]
    rows.extend(e.to_csv_row() for e in result.images_without_annotations)
    return rows


def fetch_annotations(
    project_id: int,
    cfg: CvatConfig | None = None,
    *,
    completed_only: bool = False,
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
    )
    rows = _project_annotations_to_csv_rows(result)
    if not rows:
        return pd.DataFrame(columns=list(BBoxAnnotation.model_fields.keys()))
    return pd.DataFrame(rows)

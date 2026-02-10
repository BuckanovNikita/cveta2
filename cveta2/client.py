"""CVAT client logic: connect, fetch annotations, extract shapes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cvat_sdk
from cvat_sdk import make_client
from loguru import logger

from cveta2.config import CvatConfig
from cveta2.models import BBoxAnnotation, DeletedImage, ProjectAnnotations

if TYPE_CHECKING:
    from collections.abc import Callable

_RECTANGLE = "rectangle"


# ---------------------------------------------------------------------------
# Internal context
# ---------------------------------------------------------------------------


@dataclass
class _TaskContext:
    """Shared context for extracting annotations from a single task."""

    frames: dict[int, Any]
    label_names: dict[int, str]
    attr_names: dict[int, str]
    task_id: int
    task_name: str
    task_status: str
    task_updated_date: str
    subset: str


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
            project = client.projects.retrieve(project_id)
            logger.info(f"Project: {project.name} (id={project.id})")
            logger.debug(f"Project structure from API: {project}")

            label_names, attr_names = self._build_label_maps(project)

            tasks = project.get_tasks()
            logger.debug(f"Tasks structure from API: {tasks}")
            if completed_only:
                tasks = [t for t in tasks if getattr(t, "status", None) == "completed"]
                logger.info(f"Filtered to {len(tasks)} completed task(s)")
                logger.debug(f"Completed tasks structure from API: {tasks}")
            if not tasks:
                logger.warning("No tasks in this project.")
                return ProjectAnnotations(annotations=[], deleted_images=[])

            all_annotations: list[BBoxAnnotation] = []
            all_deleted: list[DeletedImage] = []

            for task in tasks:
                logger.info(f"Processing task {task.id} ({task.name})")
                logger.trace(f"Task structure from API: {task}")

                data_meta, _ = client.api_client.tasks_api.retrieve_data_meta(
                    task.id,
                )
                logger.debug(f"Task data_meta structure from API: {data_meta}")
                frames: dict[int, Any] = dict(enumerate(data_meta.frames or []))
                logger.trace(
                    f"Task frames structure from API: {data_meta.frames or []}",
                )

                # Deleted frames
                logger.trace(
                    f"Task deleted_frames structure from API: "
                    f"{data_meta.deleted_frames or []}",
                )
                for frame_id in data_meta.deleted_frames or []:
                    frame_info = frames.get(frame_id)
                    all_deleted.append(
                        DeletedImage(
                            task_id=task.id,
                            task_name=task.name,
                            frame_id=frame_id,
                            image_name=(frame_info.name if frame_info else "<unknown>"),
                        ),
                    )

                # Annotations
                labeled_data, _ = client.api_client.tasks_api.retrieve_annotations(
                    task.id,
                )
                logger.debug(
                    f"Task annotations structure from API: {labeled_data}",
                )
                task_status = str(getattr(task, "status", "") or "")
                task_updated_date_raw = getattr(task, "updated_date", None) or getattr(
                    task, "updated_at", None
                )
                if task_updated_date_raw is None:
                    task_updated_date = ""
                elif hasattr(task_updated_date_raw, "isoformat"):
                    task_updated_date = task_updated_date_raw.isoformat()
                else:
                    task_updated_date = str(task_updated_date_raw)
                ctx = _TaskContext(
                    frames=frames,
                    label_names=label_names,
                    attr_names=attr_names,
                    task_id=task.id,
                    task_name=task.name,
                    task_status=task_status,
                    task_updated_date=task_updated_date,
                    subset=task.subset or "",
                )

                all_annotations.extend(
                    self._collect_shapes(labeled_data.shapes or [], ctx),
                )
                all_annotations.extend(
                    self._collect_track_shapes(labeled_data.tracks or [], ctx),
                )

            logger.info(
                f"Fetched {len(all_annotations)} bbox annotation(s), "
                f"{len(all_deleted)} deleted image(s)",
            )
            return ProjectAnnotations(
                annotations=all_annotations,
                deleted_images=all_deleted,
            )

    def _build_client_kwargs(self, cfg: CvatConfig) -> dict[str, Any]:
        """Build keyword arguments for ``make_client`` from a resolved config."""
        kwargs: dict[str, Any] = {"host": cfg.host}
        if cfg.token:
            kwargs["access_token"] = cfg.token
        elif cfg.username and cfg.password:
            kwargs["credentials"] = (cfg.username, cfg.password)
        return kwargs

    def _resolve_attributes(
        self,
        raw_attrs: list[Any],
        attr_names: dict[int, str],
    ) -> dict[str, str]:
        """Map AttributeVal list to {attr_name: value} dict."""
        logger.trace(f"Raw attributes structure from API: {raw_attrs}")
        return {
            attr_names.get(a.spec_id, str(a.spec_id)): a.value
            for a in (raw_attrs or [])
        }

    def _resolve_creator_username(self, item: object) -> str:
        """Extract creator username from CVAT entity metadata."""
        user_obj = getattr(item, "created_by", None) or getattr(item, "owner", None)
        if user_obj is None:
            return ""

        username = getattr(user_obj, "username", None) or getattr(
            user_obj, "name", None
        )
        if username is not None:
            return str(username)

        if isinstance(user_obj, dict):
            return str(user_obj.get("username") or user_obj.get("name") or "")
        return ""

    def _build_label_maps(
        self,
        project: cvat_sdk.Project,
    ) -> tuple[dict[int, str], dict[int, str]]:
        """Build label_id -> label_name and attr spec_id -> name mappings."""
        label_names: dict[int, str] = {}
        attr_names: dict[int, str] = {}
        labels = project.get_labels()
        logger.debug(f"Project labels structure from API: {labels}")
        for label in labels:
            logger.trace(f"Label structure from API: {label}")
            label_names[label.id] = label.name
            for attr in label.attributes or []:
                logger.trace(f"Label attribute structure from API: {attr}")
                attr_names[attr.id] = attr.name
        return label_names, attr_names

    def _collect_shapes(
        self,
        shapes: list[Any],
        ctx: _TaskContext,
    ) -> list[BBoxAnnotation]:
        """Extract BBoxAnnotations from direct shapes."""
        result: list[BBoxAnnotation] = []
        for shape in shapes:
            logger.trace(f"Shape structure from API: {shape}")
            if shape.type.value != _RECTANGLE:
                logger.warning(
                    f"Skipping shape type {shape.type.value} as it's not supported."
                )
                continue
            frame_info = ctx.frames.get(shape.frame)
            if frame_info is None:
                continue
            result.append(
                BBoxAnnotation(
                    image_name=frame_info.name,
                    image_width=frame_info.width,
                    image_height=frame_info.height,
                    instance_label=ctx.label_names.get(shape.label_id, "<unknown>"),
                    bbox_x_tl=shape.points[0],
                    bbox_y_tl=shape.points[1],
                    bbox_x_br=shape.points[2],
                    bbox_y_br=shape.points[3],
                    task_id=ctx.task_id,
                    task_name=ctx.task_name,
                    task_status=ctx.task_status,
                    task_updated_date=ctx.task_updated_date,
                    created_by_username=self._resolve_creator_username(shape),
                    frame_id=shape.frame,
                    subset=ctx.subset,
                    occluded=shape.occluded,
                    z_order=shape.z_order,
                    rotation=shape.rotation,
                    source=shape.source or "",
                    annotation_id=shape.id,
                    attributes=self._resolve_attributes(
                        shape.attributes, ctx.attr_names
                    ),
                ),
            )
        return result

    def _collect_track_shapes(
        self,
        tracks: list[Any],
        ctx: _TaskContext,
    ) -> list[BBoxAnnotation]:
        """Extract BBoxAnnotations from track shapes (interpolated/linked bboxes)."""
        result: list[BBoxAnnotation] = []
        for track in tracks:
            logger.trace(f"Track structure from API: {track}")
            track_label = ctx.label_names.get(track.label_id, "<unknown>")
            for tracked_shape in track.shapes or []:
                logger.trace(f"Tracked shape structure from API: {tracked_shape}")
                if tracked_shape.type.value != _RECTANGLE:
                    continue
                if tracked_shape.outside:
                    continue
                frame_info = ctx.frames.get(tracked_shape.frame)
                if frame_info is None:
                    continue
                creator_username = self._resolve_creator_username(
                    tracked_shape,
                ) or self._resolve_creator_username(track)
                result.append(
                    BBoxAnnotation(
                        image_name=frame_info.name,
                        image_width=frame_info.width,
                        image_height=frame_info.height,
                        instance_label=track_label,
                        bbox_x_tl=tracked_shape.points[0],
                        bbox_y_tl=tracked_shape.points[1],
                        bbox_x_br=tracked_shape.points[2],
                        bbox_y_br=tracked_shape.points[3],
                        task_id=ctx.task_id,
                        task_name=ctx.task_name,
                        task_status=ctx.task_status,
                        task_updated_date=ctx.task_updated_date,
                        created_by_username=creator_username,
                        frame_id=tracked_shape.frame,
                        subset=ctx.subset,
                        occluded=tracked_shape.occluded,
                        z_order=tracked_shape.z_order,
                        rotation=tracked_shape.rotation,
                        source=track.source or "",
                        annotation_id=track.id,
                        attributes=self._resolve_attributes(
                            tracked_shape.attributes, ctx.attr_names
                        ),
                    ),
                )
        return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_annotations(
    project_id: int,
    cfg: CvatConfig | None = None,
    *,
    completed_only: bool = False,
) -> ProjectAnnotations:
    """Compatibility wrapper around ``CvatClient``."""
    resolved_cfg = cfg or CvatConfig.load()
    return CvatClient(resolved_cfg).fetch_annotations(
        project_id,
        completed_only=completed_only,
    )

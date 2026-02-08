"""CVAT client logic: connect, fetch annotations, extract shapes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cvat_sdk import make_client
from loguru import logger

from cveta2.models import BBoxAnnotation, DeletedImage, ProjectAnnotations

if TYPE_CHECKING:
    from cveta2.config import CvatConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RECTANGLE = "rectangle"


def _build_client_kwargs(cfg: CvatConfig) -> dict[str, Any]:
    """Build keyword arguments for ``make_client`` from a resolved config."""
    kwargs: dict[str, Any] = {"host": cfg.host}
    if cfg.token:
        kwargs["access_token"] = cfg.token
    elif cfg.username and cfg.password:
        kwargs["credentials"] = (cfg.username, cfg.password)
    return kwargs


def _resolve_attributes(
    raw_attrs: list[Any],
    attr_names: dict[int, str],
) -> dict[str, str]:
    """Map AttributeVal list to {attr_name: value} dict."""
    return {
        attr_names.get(a.spec_id, str(a.spec_id)): a.value for a in (raw_attrs or [])
    }


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
    subset: str


def _build_label_maps(
    project: Any,
) -> tuple[dict[int, str], dict[int, str]]:
    """Build label_id -> label_name and attr spec_id -> name mappings."""
    label_names: dict[int, str] = {}
    attr_names: dict[int, str] = {}
    for label in project.get_labels():
        label_names[label.id] = label.name
        for attr in label.attributes or []:
            attr_names[attr.id] = attr.name
    return label_names, attr_names


# ---------------------------------------------------------------------------
# Shape collectors
# ---------------------------------------------------------------------------


def _collect_shapes(
    shapes: list[Any],
    ctx: _TaskContext,
) -> list[BBoxAnnotation]:
    """Extract BBoxAnnotations from direct shapes."""
    result: list[BBoxAnnotation] = []
    for shape in shapes:
        if shape.type.value != _RECTANGLE:
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
                frame_id=shape.frame,
                subset=ctx.subset,
                occluded=shape.occluded,
                z_order=shape.z_order,
                rotation=shape.rotation,
                source=shape.source or "",
                annotation_id=shape.id,
                attributes=_resolve_attributes(shape.attributes, ctx.attr_names),
            ),
        )
    return result


def _collect_track_shapes(
    tracks: list[Any],
    ctx: _TaskContext,
) -> list[BBoxAnnotation]:
    """Extract BBoxAnnotations from track shapes (interpolated/linked bboxes)."""
    result: list[BBoxAnnotation] = []
    for track in tracks:
        track_label = ctx.label_names.get(track.label_id, "<unknown>")
        for tracked_shape in track.shapes or []:
            if tracked_shape.type.value != _RECTANGLE:
                continue
            if tracked_shape.outside:
                continue
            frame_info = ctx.frames.get(tracked_shape.frame)
            if frame_info is None:
                continue
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
                    frame_id=tracked_shape.frame,
                    subset=ctx.subset,
                    occluded=tracked_shape.occluded,
                    z_order=tracked_shape.z_order,
                    rotation=tracked_shape.rotation,
                    source=track.source or "",
                    annotation_id=track.id,
                    attributes=_resolve_attributes(
                        tracked_shape.attributes, ctx.attr_names
                    ),
                ),
            )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_annotations(
    cfg: CvatConfig,
    project_id: int,
) -> ProjectAnnotations:
    """Fetch all bounding-box annotations and deleted images from a CVAT project.

    Returns a ``ProjectAnnotations`` with one ``BBoxAnnotation`` per bounding
    box and a flat list of ``DeletedImage`` records.
    """
    resolved = cfg.ensure_credentials()
    client_kwargs = _build_client_kwargs(resolved)

    with make_client(**client_kwargs) as client:
        project = client.projects.retrieve(project_id)
        logger.info(f"Project: {project.name} (id={project.id})")

        label_names, attr_names = _build_label_maps(project)

        tasks = project.get_tasks()
        if not tasks:
            logger.warning("No tasks in this project.")
            return ProjectAnnotations(annotations=[], deleted_images=[])

        all_annotations: list[BBoxAnnotation] = []
        all_deleted: list[DeletedImage] = []

        for task in tasks:
            logger.info(f"Processing task {task.id} ({task.name})")

            data_meta, _ = client.api_client.tasks_api.retrieve_data_meta(
                task.id,
            )
            frames: dict[int, Any] = dict(enumerate(data_meta.frames or []))

            # Deleted frames
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
            labeled_data, _ = client.api_client.tasks_api.retrieve_annotations(task.id)
            ctx = _TaskContext(
                frames=frames,
                label_names=label_names,
                attr_names=attr_names,
                task_id=task.id,
                task_name=task.name,
                subset=task.subset or "",
            )

            all_annotations.extend(
                _collect_shapes(labeled_data.shapes or [], ctx),
            )
            all_annotations.extend(
                _collect_track_shapes(labeled_data.tracks or [], ctx),
            )

        logger.info(
            f"Fetched {len(all_annotations)} bbox annotation(s), "
            f"{len(all_deleted)} deleted image(s)",
        )
        return ProjectAnnotations(
            annotations=all_annotations,
            deleted_images=all_deleted,
        )

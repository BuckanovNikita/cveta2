"""Internal conversion helpers from CVAT SDK entities to pydantic models."""

from __future__ import annotations

from typing import Any

from loguru import logger

from cveta2._client.context import _RECTANGLE, _TaskContext
from cveta2._client.mapping import _resolve_attributes, _resolve_creator_username
from cveta2.models import BBoxAnnotation


def _collect_shapes(
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
                created_by_username=_resolve_creator_username(shape),
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
            creator_username = _resolve_creator_username(
                tracked_shape,
            ) or _resolve_creator_username(track)
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
                    attributes=_resolve_attributes(
                        tracked_shape.attributes, ctx.attr_names
                    ),
                ),
            )
    return result

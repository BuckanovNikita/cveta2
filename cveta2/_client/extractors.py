"""Internal conversion helpers from typed DTOs to pydantic annotation models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from cveta2._client.context import _RECTANGLE, _TaskContext
from cveta2.models import BBoxAnnotation

if TYPE_CHECKING:
    from cveta2._client.dtos import RawShape


def _collect_shapes(
    shapes: list[RawShape],
    ctx: _TaskContext,
) -> list[BBoxAnnotation]:
    """Extract BBoxAnnotations from direct shapes."""
    result: list[BBoxAnnotation] = []
    for shape in shapes:
        if shape.type != _RECTANGLE:
            logger.warning(f"Skipping shape type {shape.type} as it's not supported.")
            continue
        frame_info = ctx.frames.get(shape.frame)
        if frame_info is None:
            continue
        issue_text, issue_state = ctx.frame_issues.get(shape.frame, ("", ""))
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
                created_by_username=shape.created_by,
                frame_id=shape.frame,
                subset=ctx.subset,
                occluded=shape.occluded,
                z_order=shape.z_order,
                rotation=shape.rotation,
                source=shape.source,
                annotation_id=shape.id,
                issue_text=issue_text,
                issue_state=issue_state,
                attributes={
                    ctx.attr_names.get(a.spec_id, str(a.spec_id)): a.value
                    for a in shape.attributes
                },
            ),
        )
    return result

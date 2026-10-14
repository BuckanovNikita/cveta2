"""Internal conversion helpers from typed DTOs to pydantic annotation models."""

import math

from loguru import logger

from cveta2.application.client.context import _RECTANGLE, _TaskContext
from cveta2.application.ports.dtos import RawShape
from cveta2.domain.models import BBoxAnnotation

_MIN_POLYGON_COORDINATES = 6


def _polygon_bounds(points: list[float]) -> tuple[float, float, float, float]:
    """Return the vertex envelope, rejecting malformed coordinate sequences."""
    if len(points) < _MIN_POLYGON_COORDINATES:
        raise ValueError("менее трёх пар координат")
    if len(points) % 2:
        raise ValueError("нечётное число координат")
    if not all(math.isfinite(value) for value in points):
        raise ValueError("нечисловые или бесконечные координаты")
    xs = points[::2]
    ys = points[1::2]
    bounds = (min(xs), min(ys), max(xs), max(ys))
    if bounds[0] == bounds[2]:
        raise ValueError("нулевая ширина ограничивающего прямоугольника")
    if bounds[1] == bounds[3]:
        raise ValueError("нулевая высота ограничивающего прямоугольника")
    return bounds


def _collect_shapes(
    shapes: list[RawShape],
    ctx: _TaskContext,
) -> list[BBoxAnnotation]:
    """Extract BBoxAnnotations from direct shapes."""
    result: list[BBoxAnnotation] = []
    skipped_polygons = 0
    for shape in shapes:
        if shape.type not in (_RECTANGLE, "polygon"):
            logger.warning(f"Skipping shape type {shape.type} as it's not supported.")
            continue
        frame_info = ctx.frames.get(shape.frame)
        if frame_info is None:
            continue
        if shape.type == "polygon":
            try:
                x_tl, y_tl, x_br, y_br = _polygon_bounds(shape.points)
            except ValueError as error:
                skipped_polygons += 1
                logger.warning(
                    f"Задача {ctx.task_id}, аннотация {shape.id}: "
                    f"полигон пропущен: {error}"
                )
                continue
            rotation = 0.0
            logger.warning(
                f"Задача {ctx.task_id}, аннотация {shape.id}: полигон преобразован "
                f"в ограничивающий прямоугольник; это приближение исходного контура"
            )
        else:
            x_tl, y_tl, x_br, y_br = (
                shape.points[0],
                shape.points[1],
                shape.points[2],
                shape.points[3],
            )
            rotation = shape.rotation
        issue_text, issue_state = ctx.frame_issues.get(shape.frame, ("", ""))
        job_stage, job_state = ctx.job_position(shape.frame)
        result.append(
            BBoxAnnotation(
                image_name=frame_info.name,
                image_width=frame_info.width,
                image_height=frame_info.height,
                instance_label=ctx.label_names.get(shape.label_id, "<unknown>"),
                bbox_x_tl=x_tl,
                bbox_y_tl=y_tl,
                bbox_x_br=x_br,
                bbox_y_br=y_br,
                task_id=ctx.task_id,
                task_name=ctx.task_name,
                job_stage=job_stage,
                job_state=job_state,
                task_completed=ctx.task_completed,
                task_updated_date=ctx.task_updated_date,
                created_by_username=shape.created_by,
                frame_id=shape.frame,
                subset=ctx.subset,
                occluded=shape.occluded,
                z_order=shape.z_order,
                rotation=rotation,
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
    if skipped_polygons:
        logger.warning(f"Задача {ctx.task_id}: пропущено полигонов: {skipped_polygons}")
    return result

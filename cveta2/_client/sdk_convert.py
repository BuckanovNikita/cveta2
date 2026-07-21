"""Pure CVAT SDK object → DTO converters (no I/O, no client state).

Split out of :mod:`cveta2._client.sdk_adapter` so the adapter holds only
"call SDK, translate errors" logic and these transforms stay testable
without a client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cveta2._client.dtos import (
    RawAnnotations,
    RawAttribute,
    RawDataMeta,
    RawFrame,
    RawShape,
)
from cveta2.models import LabelAttributeInfo, LabelInfo, TaskInfo

if TYPE_CHECKING:
    from cvat_sdk.api_client import models as cvat_models


def convert_task(task: cvat_models.TaskRead) -> TaskInfo:
    """Convert an SDK task to :class:`TaskInfo`."""
    return TaskInfo(
        id=task.id,
        name=task.name or "",
        status=str(task.status or ""),
        subset=task.subset or "",
        updated_date=extract_updated_date(task),
    )


def extract_updated_date(task: cvat_models.TaskRead) -> str:
    """Normalize ``updated_date`` / ``updated_at`` to ISO string.

    Uses ``getattr`` because the CVAT SDK renamed ``updated_date`` to
    ``updated_at`` between versions, and the returned value may be a
    ``datetime`` (with ``.isoformat()``) or a plain string depending on
    the SDK release.  This is an intentional exception to the project
    style rule "avoid getattr" (see CLAUDE.md).
    """
    raw: object | None = getattr(task, "updated_date", None)
    if raw is None:
        raw = getattr(task, "updated_at", None)
    if raw is None:
        return ""
    isoformat = getattr(raw, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(raw)


def convert_label(label: cvat_models.Label) -> LabelInfo:
    """Convert an SDK label to :class:`LabelInfo`."""
    raw_attrs = label.attributes or []
    attrs = [LabelAttributeInfo(id=a.id, name=a.name or "") for a in raw_attrs]
    return LabelInfo(
        id=label.id, name=label.name, attributes=attrs, color=label.color or ""
    )


def _raw_frame(name: object, width: object, height: object) -> RawFrame:
    """Build a :class:`RawFrame` from loosely-typed SDK/JSON field values."""
    return RawFrame(
        name=str(name or ""),
        width=int(width or 0),  # type: ignore[call-overload]
        height=int(height or 0),  # type: ignore[call-overload]
    )


def convert_data_meta(data_meta: cvat_models.DataMetaRead) -> RawDataMeta:
    """Convert SDK data-meta (frames + deleted frame ids) to :class:`RawDataMeta`."""
    frames = [_raw_frame(f.name, f.width, f.height) for f in (data_meta.frames or [])]
    return RawDataMeta(
        frames=frames, deleted_frames=list(data_meta.deleted_frames or [])
    )


def data_meta_from_dict(data: dict[str, Any]) -> RawDataMeta:
    """Build RawDataMeta from API response dict when SDK deserialization fails."""
    frames = [
        _raw_frame(f.get("name"), f.get("width"), f.get("height"))
        for f in (data.get("frames") or [])
    ]
    return RawDataMeta(
        frames=frames, deleted_frames=list(data.get("deleted_frames") or [])
    )


def convert_annotations(labeled_data: cvat_models.LabeledData) -> RawAnnotations:
    """Convert SDK labeled data to :class:`RawAnnotations`."""
    return RawAnnotations(
        shapes=[convert_shape(s) for s in (labeled_data.shapes or [])]
    )


def convert_shape(shape: cvat_models.LabeledShape) -> RawShape:
    """Convert an SDK labeled shape to :class:`RawShape`."""
    type_val = shape.type.value if shape.type else str(shape.type)
    return RawShape(
        id=shape.id or 0,
        type=type_val,
        frame=shape.frame,
        label_id=shape.label_id,
        points=list(shape.points or []),
        occluded=bool(shape.occluded),
        z_order=int(shape.z_order or 0),
        rotation=float(shape.rotation or 0.0),
        source=str(shape.source or ""),
        attributes=convert_attributes(shape.attributes),
        created_by=extract_creator_username(shape),
    )


def convert_attributes(
    raw_attrs: list[cvat_models.AttributeVal] | None,
) -> list[RawAttribute]:
    """Convert SDK attribute values to :class:`RawAttribute` list."""
    if not raw_attrs:
        return []
    return [
        RawAttribute(spec_id=a.spec_id, value=str(a.value or "")) for a in raw_attrs
    ]


def extract_creator_username(item: object) -> str:
    """Extract creator username from a CVAT SDK entity.

    Uses ``getattr`` because the CVAT SDK represents the creator
    inconsistently across entity types and versions: ``created_by`` may
    be a user object, a dict, or absent (in which case ``owner`` is
    used).  The user object itself may expose ``username`` or ``name``.
    This is an intentional exception to the project style rule
    "avoid getattr" (see CLAUDE.md).
    """
    user_obj = getattr(item, "created_by", None) or getattr(item, "owner", None)
    if user_obj is None:
        return ""
    username = getattr(user_obj, "username", None) or getattr(user_obj, "name", None)
    if username is not None:
        return str(username)
    if isinstance(user_obj, dict):
        return str(user_obj.get("username") or user_obj.get("name") or "")
    return ""

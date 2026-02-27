"""Typed data-transfer objects for internal CVAT API responses.

These simple dataclasses represent raw data consumed from the CVAT SDK,
providing a typed boundary that is trivial to construct in tests.

Domain-level types that cross layer boundaries (``TaskInfo``,
``LabelInfo``, ``ProjectInfo``) live in :mod:`cveta2.models`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RawFrame:
    """Single frame (image) metadata from a CVAT task."""

    name: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RawAttribute:
    """Attribute value attached to a shape or tracked shape."""

    spec_id: int
    value: str


@dataclass(frozen=True, slots=True)
class RawShape:
    """A single shape (annotation) from CVAT labeled data."""

    id: int
    type: str
    frame: int
    label_id: int
    points: list[float]
    occluded: bool
    z_order: int
    rotation: float
    source: str
    attributes: list[RawAttribute]
    created_by: str


@dataclass(frozen=True, slots=True)
class RawDataMeta:
    """Frame list and deleted frame IDs for a task."""

    frames: list[RawFrame]
    deleted_frames: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RawAnnotations:
    """Shapes for a task."""

    shapes: list[RawShape] = field(default_factory=list)

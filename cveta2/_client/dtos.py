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


@dataclass(frozen=True, slots=True)
class RawIssue:
    """A review issue attached to a task frame, with its comment texts."""

    id: int
    frame: int
    resolved: bool
    comments: list[str]
    position: list[float] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RawJob:
    """A CVAT job with its frame range and review position.

    ``stage`` and ``state`` default to empty so the write paths, which
    build jobs only to address them, need not invent a review position.
    """

    id: int
    start_frame: int
    stop_frame: int
    stage: str = ""
    state: str = ""
    type: str = "annotation"


@dataclass(frozen=True, slots=True)
class NewShape:
    """A new rectangle annotation to upload to a task."""

    frame: int
    label_id: int
    points: list[float]
    type: str = "rectangle"


@dataclass(frozen=True, slots=True)
class NewIssue:
    """A new review issue to open on a job frame."""

    job_id: int
    frame: int
    position: list[float]
    message: str


@dataclass(frozen=True, slots=True)
class LabelPatch:
    """A single label change for a project PATCH request.

    ``id=None`` creates a new label named *name*; with ``id`` set, the
    non-``None`` fields are updated (``deleted=True`` removes the label).
    """

    id: int | None = None
    name: str | None = None
    color: str | None = None
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class UploadTaskSpec:
    """Specification for creating a task backed by cloud-storage images."""

    project_id: int
    name: str
    server_files: list[str]
    cloud_storage_id: int
    segment_size: int = 100
    image_quality: int = 100

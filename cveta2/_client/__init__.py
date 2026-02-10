"""Internal helpers for splitting `cveta2.client` responsibilities."""

from cveta2._client.context import _RECTANGLE, _TaskContext
from cveta2._client.extractors import _collect_shapes, _collect_track_shapes
from cveta2._client.mapping import (
    _build_label_maps,
    _resolve_attributes,
    _resolve_creator_username,
)

__all__ = [
    "_RECTANGLE",
    "_TaskContext",
    "_build_label_maps",
    "_collect_shapes",
    "_collect_track_shapes",
    "_resolve_attributes",
    "_resolve_creator_username",
]

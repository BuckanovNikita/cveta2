"""Internal helpers for splitting `cveta2.client` responsibilities."""

from cveta2._client.context import _RECTANGLE, _TaskContext
from cveta2._client.dtos import (
    RawAnnotations,
    RawAttribute,
    RawDataMeta,
    RawFrame,
    RawShape,
    RawTrack,
    RawTrackedShape,
)
from cveta2._client.extractors import _collect_shapes
from cveta2._client.mapping import (
    _build_label_maps,
    _resolve_attributes,
)
from cveta2._client.ports import CvatApiPort
from cveta2._client.sdk_adapter import SdkCvatApiAdapter

__all__ = [
    "_RECTANGLE",
    "CvatApiPort",
    "RawAnnotations",
    "RawAttribute",
    "RawDataMeta",
    "RawFrame",
    "RawShape",
    "RawTrack",
    "RawTrackedShape",
    "SdkCvatApiAdapter",
    "_TaskContext",
    "_build_label_maps",
    "_collect_shapes",
    "_resolve_attributes",
]

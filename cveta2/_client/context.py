"""Internal data structures used while processing a CVAT task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_RECTANGLE = "rectangle"


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

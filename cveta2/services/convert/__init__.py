"""Conversion services between cveta2 CSV and YOLO/COCO detection formats."""

from __future__ import annotations

from cveta2.services.convert.coco import convert_to_coco
from cveta2.services.convert.yolo import convert_from_yolo, convert_to_yolo

__all__ = [
    "convert_from_yolo",
    "convert_to_coco",
    "convert_to_yolo",
]

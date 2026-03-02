"""Internal helpers for resolving labels and attributes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from cveta2.models import LabelInfo


def _build_label_maps(
    labels: list[LabelInfo],
) -> tuple[dict[int, str], dict[int, str]]:
    """Build label_id -> label_name and attr spec_id -> name mappings."""
    label_names: dict[int, str] = {}
    attr_names: dict[int, str] = {}
    for label in labels:
        logger.trace(f"Label: id={label.id} name={label.name}")
        label_names[label.id] = label.name
        for attr in label.attributes:
            logger.trace(f"Label attribute: id={attr.id} name={attr.name}")
            attr_names[attr.id] = attr.name
    return label_names, attr_names

"""Internal helpers for resolving labels and attributes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from cveta2._client.dtos import RawAttribute, RawLabel


def _attr_display_name(attr_names: dict[int, str], spec_id: int) -> str:
    """Return attribute display name by spec_id, or str(spec_id) if unknown."""
    return attr_names.get(spec_id, str(spec_id))


def _resolve_attributes(
    raw_attrs: list[RawAttribute],
    attr_names: dict[int, str],
) -> dict[str, str]:
    """Map RawAttribute list to {attr_name: value} dict."""
    logger.trace(f"Resolving attributes: {raw_attrs}")
    return {_attr_display_name(attr_names, a.spec_id): a.value for a in raw_attrs}


def _build_label_maps(
    labels: list[RawLabel],
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

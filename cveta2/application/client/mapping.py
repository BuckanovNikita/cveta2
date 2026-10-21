"""Internal helpers for resolving labels and attributes."""

from typing import TYPE_CHECKING

from loguru import logger

from cveta2.domain.paths import names_with_basename_fallback

if TYPE_CHECKING:
    from cveta2.application.ports.dtos import RawDataMeta
    from cveta2.domain.models import LabelInfo


def _build_label_maps(
    labels: "list[LabelInfo]",
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


def build_name_to_frame(data_meta: "RawDataMeta") -> dict[str, int]:
    """Build frame-name -> frame-index mapping (with basename fallback)."""
    return names_with_basename_fallback(
        (frame.name, idx) for idx, frame in enumerate(data_meta.frames)
    )

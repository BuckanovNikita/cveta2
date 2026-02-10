"""Internal helpers for resolving labels, attributes, and usernames."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import cvat_sdk


def _resolve_attributes(
    raw_attrs: list[Any],
    attr_names: dict[int, str],
) -> dict[str, str]:
    """Map AttributeVal list to {attr_name: value} dict."""
    logger.trace(f"Raw attributes structure from API: {raw_attrs}")
    return {
        attr_names.get(a.spec_id, str(a.spec_id)): a.value for a in (raw_attrs or [])
    }


def _resolve_creator_username(item: object) -> str:
    """Extract creator username from CVAT entity metadata."""
    user_obj = getattr(item, "created_by", None) or getattr(item, "owner", None)
    if user_obj is None:
        return ""

    username = getattr(user_obj, "username", None) or getattr(user_obj, "name", None)
    if username is not None:
        return str(username)

    if isinstance(user_obj, dict):
        return str(user_obj.get("username") or user_obj.get("name") or "")
    return ""


def _build_label_maps(
    project: cvat_sdk.Project,
) -> tuple[dict[int, str], dict[int, str]]:
    """Build label_id -> label_name and attr spec_id -> name mappings."""
    label_names: dict[int, str] = {}
    attr_names: dict[int, str] = {}
    labels = project.get_labels()
    logger.debug(f"Project labels structure from API: {labels}")
    for label in labels:
        logger.trace(f"Label structure from API: {label}")
        label_names[label.id] = label.name
        for attr in label.attributes or []:
            logger.trace(f"Label attribute structure from API: {attr}")
            attr_names[attr.id] = attr.name
    return label_names, attr_names

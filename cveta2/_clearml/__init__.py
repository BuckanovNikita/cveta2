"""ClearML integration — optional dataset publishing after fetch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from cveta2.config import is_clearml_disabled, load_clearml_config

if TYPE_CHECKING:
    from pathlib import Path


def is_clearml_available() -> bool:
    """Return True if the ``clearml`` package is importable."""
    try:
        import clearml  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def maybe_publish_clearml(project_name: str, output_dir: Path) -> None:
    """Publish CSV files to ClearML Dataset if configured.

    This is the single entry point called from fetch.py.
    All guard checks and error handling live here so the caller
    needs no ClearML awareness.
    """
    if is_clearml_disabled():
        logger.debug("ClearML disabled via CVETA2_CLEARML=false")
        return

    if not is_clearml_available():
        logger.debug("ClearML package not installed — skipping dataset publish")
        return

    cfg = load_clearml_config()
    if not cfg.enabled:
        logger.debug("ClearML disabled in config")
        return

    mapping = cfg.get_mapping(project_name)
    if mapping is None:
        logger.debug(
            f"No ClearML mapping for project {project_name!r} — skipping publish"
        )
        return

    try:
        from cveta2._clearml._dataset import publish_to_clearml  # noqa: PLC0415

        publish_to_clearml(mapping, output_dir)
    except Exception:  # noqa: BLE001
        logger.warning(
            f"ClearML publish failed for project {project_name!r} — "
            "fetch results are unaffected",
            exc_info=True,
        )

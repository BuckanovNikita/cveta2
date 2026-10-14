"""ClearML integration — optional dataset publishing after fetch."""

from typing import TYPE_CHECKING

from loguru import logger

from cveta2.adapters.clearml.availability import is_clearml_available
from cveta2.adapters.config.settings import ClearmlConfig, is_clearml_disabled
from cveta2.domain.errors import ClearmlPublishError

if TYPE_CHECKING:
    from pathlib import Path


def maybe_publish_clearml(
    project_name: str, output_dir: "Path", config_path: "Path | None" = None
) -> None:
    """Publish CSV files to ClearML Dataset if configured.

    This is the single entry point called from fetch.py.
    All guard checks and error handling live here so the caller
    needs no ClearML awareness. ``config_path`` selects the config file
    the ``clearml`` section is read from; None means the default one.
    """
    if is_clearml_disabled():
        logger.debug("ClearML disabled via CVETA2_CLEARML=false")
        return

    if not is_clearml_available():
        logger.debug("ClearML package not installed — skipping dataset publish")
        return

    cfg = ClearmlConfig.load(config_path)
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
        from cveta2.adapters.clearml._dataset import publish_to_clearml  # noqa: PLC0415

        publish_to_clearml(mapping, output_dir)
    except (ClearmlPublishError, ImportError):
        logger.opt(exception=True).warning(
            f"ClearML publish failed for project {project_name!r} — "
            "fetch results are unaffected"
        )

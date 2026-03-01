"""ClearML Dataset SDK wrapper — lazy-imports clearml."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.config import ClearmlProjectMapping


def publish_to_clearml(mapping: ClearmlProjectMapping, output_dir: Path) -> None:
    """Create a new ClearML Dataset version with CSV files from *output_dir*."""
    from clearml import Dataset  # noqa: PLC0415

    csv_files = sorted(output_dir.glob("*.csv"))
    if not csv_files:
        logger.info("No CSV files in output directory — nothing to publish to ClearML")
        return

    logger.info(
        f"Publishing {len(csv_files)} CSV files to ClearML "
        f"(project={mapping.clearml_project!r}, dataset={mapping.clearml_dataset!r})"
    )

    dataset = Dataset.create(
        dataset_project=mapping.clearml_project,
        dataset_name=mapping.clearml_dataset,
    )
    for csv_file in csv_files:
        dataset.add_files(str(csv_file))

    dataset.upload()
    dataset.finalize()

    logger.info(f"ClearML Dataset published: id={dataset.id}")

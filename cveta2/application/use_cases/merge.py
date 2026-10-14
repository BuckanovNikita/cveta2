"""Merge orchestration over an explicit dataset persistence port."""

from pathlib import Path

import pandas as pd

from cveta2.application.ports.dataset import DatasetFiles
from cveta2.domain.merge import _merge_datasets

_REQUIRED_COLUMNS = {
    "bbox_y_tl",
    "bbox_x_br",
    "instance_shape",
    "bbox_y_br",
    "bbox_x_tl",
    "instance_label",
    "image_name",
}


def merge_datasets(  # noqa: PLR0913
    old: str | Path,
    new: str | Path,
    output: str | Path,
    *,
    deleted: str | Path | None = None,
    by_task: bool = False,
    files: DatasetFiles,
) -> pd.DataFrame:
    """Merge two dataset CSVs and write the result to *output*.

    Returns the merged DataFrame.
    """
    old_df = files.read_dataset_csv(
        Path(old), _REQUIRED_COLUMNS, require_task_id_column=by_task
    )
    new_df = files.read_dataset_csv(
        Path(new), _REQUIRED_COLUMNS, require_task_id_column=by_task
    )
    deleted_names = files.read_deleted_names(Path(deleted) if deleted else None)

    merged = _merge_datasets(old_df, new_df, deleted_names, by_task=by_task)

    output_path = Path(output)
    files.save_csv(merged, output_path)
    return merged

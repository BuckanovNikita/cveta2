"""CSV writers and record path population shared by fetch/upload workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2.exceptions import Cveta2Error
from cveta2.models import CSV_COLUMNS
from cveta2.s3_utils import build_s3_key

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from cveta2.dataset_partition import PartitionResult
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import DeletedImage, ProjectAnnotations


def read_dataset_csv(
    path: Path,
    required_columns: set[str],
    *,
    require_time_column: bool = False,
) -> pd.DataFrame:
    """Read a dataset CSV and validate required columns.

    Raises ``Cveta2Error`` if the file is missing or columns are invalid.
    When *require_time_column* is True, ``task_updated_date`` must also be present.
    """
    if not path.is_file():
        raise Cveta2Error(f"Ошибка: файл не найден: {path}")
    df = pd.read_csv(path, encoding="utf-8")
    missing = required_columns - set(df.columns)
    if missing:
        raise Cveta2Error(
            f"Ошибка: в {path} отсутствуют обязательные столбцы: "
            f"{', '.join(sorted(missing))}"
        )
    if require_time_column and "task_updated_date" not in df.columns:
        raise Cveta2Error(
            f"Ошибка: --by-time требует столбец 'task_updated_date' "
            f"в {path}, но он отсутствует."
        )
    logger.info(f"Загружен {path}: {len(df)} строк")
    return df


def populate_record_paths(
    result: ProjectAnnotations,
    cs_info: CloudStorageInfo | None,
    images_dir: Path | None,
) -> None:
    """Set ``s3_image_path`` and ``image_path`` on all annotation/deleted records."""
    for record in (*result.annotations, *result.deleted_images):
        if cs_info is not None:
            record.s3_image_path = build_s3_key(cs_info.prefix, record.image_name)
        if images_dir is not None:
            local = images_dir / record.image_name
            if local.exists():
                record.image_path = str(local.resolve())


def enrich_dataframe_paths(
    df: pd.DataFrame,
    cs_info: CloudStorageInfo,
    found_images: dict[str, Path],
    name_to_server_file: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Add ``s3_image_path`` and ``image_path`` columns to the DataFrame."""
    df = df.copy()
    df["s3_image_path"] = df["image_name"].map(
        lambda name: build_s3_key(
            cs_info.prefix,
            name_to_server_file[name]
            if name_to_server_file and name in name_to_server_file
            else name,
        )
    )
    df["image_path"] = df["image_name"].map(
        lambda name: str(found_images[name].resolve()) if name in found_images else None
    )
    return df


def count_images(df: pd.DataFrame) -> int:
    """Count unique images in an annotation DataFrame (0 when empty)."""
    if "image_name" not in df.columns:
        return 0
    return int(df["image_name"].nunique())


def write_raw_csv(result: ProjectAnnotations, output_dir: Path) -> None:
    """Write raw.csv with all annotation and deleted rows, unpartitioned."""
    rows = result.to_csv_rows()
    deleted_rows = [d.to_csv_row() for d in result.deleted_images]
    raw_df = pd.DataFrame(rows + deleted_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw.csv"
    raw_df.to_csv(raw_path, index=False, encoding="utf-8")
    logger.info(
        f"Raw CSV saved to {raw_path} "
        f"({count_images(raw_df)} images, {len(raw_df)} rows)"
    )


def _write_deleted_csv(
    deleted_images: Sequence[DeletedImage], output_dir: Path
) -> None:
    """Write deleted.csv with full CSV columns (empty frame when no rows)."""
    deleted_rows = [img.to_csv_row() for img in deleted_images]
    deleted_df = (
        pd.DataFrame(deleted_rows, columns=list(CSV_COLUMNS))
        if deleted_rows
        else pd.DataFrame(columns=list(CSV_COLUMNS))
    )
    deleted_path = output_dir / "deleted.csv"
    deleted_df.to_csv(deleted_path, index=False, encoding="utf-8")
    logger.info(f"Deleted CSV saved to {deleted_path} ({len(deleted_df)} rows)")


def write_partition_csvs(partition: PartitionResult, output_dir: Path) -> None:
    """Write dataset/obsolete/in_progress CSVs and deleted.csv into *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for df, name, label in [
        (partition.dataset, "dataset.csv", "Dataset CSV"),
        (partition.obsolete, "obsolete.csv", "Obsolete CSV"),
        (partition.in_progress, "in_progress.csv", "In-progress CSV"),
    ]:
        path = output_dir / name
        df.to_csv(path, index=False, encoding="utf-8")
        logger.info(
            f"{label} saved to {path} ({count_images(df)} images, {len(df)} rows)"
        )

    _write_deleted_csv(partition.deleted_images, output_dir)


def write_dataset_and_deleted(result: ProjectAnnotations, output_dir: Path) -> None:
    """Write dataset.csv and deleted.csv from annotation result into *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = result.to_csv_rows()
    df = pd.DataFrame(rows)

    dataset_path = output_dir / "dataset.csv"
    df.to_csv(dataset_path, index=False, encoding="utf-8")
    logger.info(
        f"Dataset CSV saved to {dataset_path} "
        f"({count_images(df)} images, {len(df)} rows)"
    )

    _write_deleted_csv(result.deleted_images, output_dir)

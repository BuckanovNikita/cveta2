"""CSV writers and record path population shared by fetch/upload workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import pandas as pd
from loguru import logger

from cveta2.exceptions import Cveta2Error
from cveta2.models import CSV_COLUMNS
from cveta2.s3_utils import build_s3_key, strip_key_prefix

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from cveta2.dataset_partition import PartitionResult
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import DeletedImage, ProjectAnnotations

_UTF8 = "utf-8"
"""The one codec every file this project reads or writes is encoded in."""


class _CsvReadOptions(TypedDict):
    """Reader knobs shared by every CSV this project reads."""

    encoding: str


class _CsvWriteOptions(TypedDict):
    """Writer knobs shared by every CSV this project writes."""

    index: bool
    encoding: str


CSV_READ_OPTIONS: _CsvReadOptions = {"encoding": _UTF8}
CSV_WRITE_OPTIONS: _CsvWriteOptions = {"index": False, "encoding": _UTF8}


def read_text_utf8(path: Path) -> str:
    """Read *path* as UTF-8, independent of the platform's locale encoding."""
    return path.read_bytes().decode(_UTF8)


def write_text_utf8(path: Path, text: str) -> None:
    r"""Write *text* to *path* as UTF-8, independent of the locale encoding.

    Going through bytes also pins the line endings: text mode would
    translate ``\n`` to ``\r\n`` on Windows, which YOLO label files and
    ``dataset.yaml`` must not depend on.
    """
    path.write_bytes(text.encode(_UTF8))


def read_dataset_csv(
    path: Path,
    required_columns: set[str],
    *,
    require_task_id_column: bool = False,
) -> pd.DataFrame:
    """Read a dataset CSV and validate required columns.

    Raises ``Cveta2Error`` if the file is missing or columns are invalid.
    When *require_task_id_column* is True, ``task_id`` must also be present.
    """
    if not path.is_file():
        raise Cveta2Error(f"Ошибка: файл не найден: {path}")
    df = pd.read_csv(path, **CSV_READ_OPTIONS)
    missing = required_columns - set(df.columns)
    if missing:
        raise Cveta2Error(
            f"Ошибка: в {path} отсутствуют обязательные столбцы: "
            f"{', '.join(sorted(missing))}"
        )
    if require_task_id_column and "task_id" not in df.columns:
        raise Cveta2Error(
            f"Ошибка: --by-task требует столбец 'task_id' в {path}, но он отсутствует."
        )
    logger.info(f"Загружен {path}: {len(df)} строк")
    return df


def populate_record_paths(
    result: ProjectAnnotations,
    cs_info: CloudStorageInfo | None,
    images_dir: Path | None,
    ignored_prefix: str | None = None,
) -> None:
    """Set ``s3_image_path`` and ``image_path`` on all annotation/deleted records.

    ``s3_image_path`` is built from the full frame key (``frame_path`` when
    the CVAT frame name was nested).  The local path mirrors the S3 layout
    below the storage prefix; with *ignored_prefix* set, only that leading
    key part is stripped instead (keeping more of the S3 hierarchy).

    Records are per annotation, not per image, so an image carrying ten
    boxes used to cost ten identical ``exists``/``resolve`` pairs.  They are
    memoized per path instead: on a shared network cache each of those is a
    round-trip.
    """
    resolved: dict[Path, str | None] = {}
    for record in (*result.annotations, *result.deleted_images):
        frame_ref = record.frame_path or record.image_name
        if cs_info is not None:
            record.s3_image_path = build_s3_key(cs_info.prefix, frame_ref)
        if images_dir is not None:
            local_rel = frame_ref
            if ignored_prefix and cs_info is not None:
                local_rel = strip_key_prefix(
                    build_s3_key(cs_info.prefix, frame_ref), ignored_prefix
                )
            local = images_dir / local_rel
            if local not in resolved:
                resolved[local] = str(local.resolve()) if local.exists() else None
            found = resolved[local]
            if found is not None:
                record.image_path = found


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


PREVIEW_LIMIT = 10
"""How many example names log messages show before collapsing the rest."""


def preview_names(names: Sequence[str], limit: int = PREVIEW_LIMIT) -> str:
    """Format ``"a, b, c (и ещё N)"``: the first *limit* names plus a rest count."""
    shown = ", ".join(str(name) for name in names[:limit])
    extra = len(names) - limit
    return f"{shown} (и ещё {extra})" if extra > 0 else shown


def count_images(df: pd.DataFrame) -> int:
    """Count unique images in an annotation DataFrame (0 when empty)."""
    if "image_name" not in df.columns:
        return 0
    return int(df["image_name"].nunique())


def format_counts(df: pd.DataFrame) -> str:
    """English ``N images, M rows`` summary for log messages."""
    return f"{count_images(df)} images, {len(df)} rows"


def format_counts_ru(df: pd.DataFrame) -> str:
    """Russian ``N изображений, M строк`` summary for log messages."""
    return f"{count_images(df)} изображений, {len(df)} строк"


CSV_LABELS: dict[str, str] = {
    "raw.csv": "Raw CSV",
    "dataset.csv": "Dataset CSV",
    "obsolete.csv": "Obsolete CSV",
    "in_progress.csv": "In-progress CSV",
    "deleted.csv": "Deleted CSV",
}
"""Human-readable name each output CSV is logged under."""


def save_csv(df: pd.DataFrame, path: Path) -> None:
    """Write *df* to *path* and log its ``CSV_LABELS`` name with row counts."""
    df.to_csv(path, **CSV_WRITE_OPTIONS)
    logger.info(
        f"{CSV_LABELS.get(path.name, path.name)} saved to {path} ({format_counts(df)})"
    )


def write_raw_csv(result: ProjectAnnotations, output_dir: Path) -> None:
    """Write raw.csv with all annotation and deleted rows, unpartitioned."""
    rows = result.to_csv_rows()
    deleted_rows = [d.to_csv_row() for d in result.deleted_images]
    output_dir.mkdir(parents=True, exist_ok=True)
    save_csv(pd.DataFrame(rows + deleted_rows), output_dir / "raw.csv")


def _write_deleted_csv(
    deleted_images: Sequence[DeletedImage], output_dir: Path
) -> None:
    """Write deleted.csv with full CSV columns (empty frame when no rows)."""
    deleted_rows = [img.to_csv_row() for img in deleted_images]
    deleted_df = pd.DataFrame(deleted_rows, columns=list(CSV_COLUMNS))
    save_csv(deleted_df, output_dir / "deleted.csv")


def write_partition_csvs(partition: PartitionResult, output_dir: Path) -> None:
    """Write dataset/obsolete/in_progress CSVs and deleted.csv into *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for df, name in [
        (partition.dataset, "dataset.csv"),
        (partition.obsolete, "obsolete.csv"),
        (partition.in_progress, "in_progress.csv"),
    ]:
        save_csv(df, output_dir / name)
    _write_deleted_csv(partition.deleted_images, output_dir)


def write_dataset_and_deleted(result: ProjectAnnotations, output_dir: Path) -> None:
    """Write dataset.csv and deleted.csv from annotation result into *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(result.to_csv_rows())
    save_csv(df, output_dir / "dataset.csv")
    _write_deleted_csv(result.deleted_images, output_dir)

"""CSV writers and record path population shared by fetch/upload workflows."""

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
from loguru import logger

from cveta2.adapters.files.materialization import _confined_destination
from cveta2.domain.baseline import SIBLING_CSV_NAMES
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import CSV_COLUMNS, DeletedImage, ProjectAnnotations
from cveta2.domain.output import (
    _UTF8,
    CSV_LABELS,
    CSV_READ_OPTIONS,
    CSV_WRITE_OPTIONS,
    format_counts,
)
from cveta2.domain.partition import PartitionResult
from cveta2.domain.paths import _canonical_frame_key, _local_name_from_key, build_s3_key
from cveta2.domain.storage import CloudStorageInfo


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

    Raises ``Cveta2Error`` if the file is missing, has no header row or
    lacks required columns.  When *require_task_id_column* is True,
    ``task_id`` must also be present.
    """
    if not path.is_file():
        raise Cveta2Error(f"Ошибка: файл не найден: {path}")
    try:
        with path.open("rb") as stream:
            if any(b"\x00" in chunk for chunk in iter(lambda: stream.read(65536), b"")):
                raise Cveta2Error(f"Ошибка: CSV {path} содержит нулевой байт")
        df = pd.read_csv(path, **CSV_READ_OPTIONS)
    except pd.errors.EmptyDataError as e:
        raise Cveta2Error(f"Ошибка: файл {path} пуст, нет даже строки заголовка") from e
    except (pd.errors.ParserError, UnicodeError, OSError) as e:
        raise Cveta2Error(f"Ошибка: не удалось прочитать CSV {path}: {e}") from e
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
        prefix = cs_info.prefix if cs_info is not None else ""
        key = record.s3_image_path or _canonical_frame_key(prefix, frame_ref)
        if cs_info is not None:
            record.s3_image_path = key
        if images_dir is not None:
            local_rel = _local_name_from_key(
                key, ignored_prefix or prefix, original=frame_ref
            )
            local = _confined_destination(images_dir, local_rel, original=frame_ref)
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


def save_csv(df: pd.DataFrame, path: Path) -> None:
    """Write *df* to *path* and log its ``CSV_LABELS`` name with row counts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, **CSV_WRITE_OPTIONS)
    logger.info(
        f"{CSV_LABELS.get(path.name, path.name)} saved to {path} ({format_counts(df)})"
    )


def write_raw_csv(result: ProjectAnnotations, output_dir: Path) -> None:
    """Write raw.csv with all annotation and deleted rows, unpartitioned."""
    rows = result.to_csv_rows()
    deleted_rows = [d.to_csv_row() for d in result.deleted_images]
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_df = pd.DataFrame(rows + deleted_rows, columns=list(CSV_COLUMNS))
    save_csv(raw_df, output_dir / "raw.csv")


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
    df = pd.DataFrame(result.to_csv_rows(), columns=list(CSV_COLUMNS))
    save_csv(df, output_dir / "dataset.csv")
    _write_deleted_csv(result.deleted_images, output_dir)


def read_deleted_names(path: Path | None) -> set[str]:
    """Read *deleted.csv* and return image names as a set.

    Supports both the new CSV format (with ``image_name`` column) and the
    legacy plain-text format (one name per line) for backward compatibility.
    """
    if path is None:
        return set()
    if not path.is_file():
        raise Cveta2Error(f"Ошибка: файл не найден: {path}")

    try:
        text = read_text_utf8(path)
    except (UnicodeError, OSError) as exc:
        raise Cveta2Error(f"Ошибка: не удалось прочитать {path}: {exc}") from exc
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or "image_name" not in lines[0]:
        legacy_names = set(lines)
        logger.info(f"Загружен {path}: {len(legacy_names)} удалённых изображений")
        return legacy_names

    df = read_dataset_csv(path, {"image_name"})
    names = set(df["image_name"].dropna().unique())
    logger.info(f"Загружен {path}: {len(names)} удалённых изображений")
    return names


def read_baseline_siblings(path: Path) -> list[pd.DataFrame]:
    """Read optional completed-task CSVs, retaining existing degradation policy."""
    frames: list[pd.DataFrame] = []
    for name in SIBLING_CSV_NAMES:
        sibling = path.parent / name
        if not sibling.is_file():
            continue
        try:
            frames.append(pd.read_csv(sibling, **CSV_READ_OPTIONS))
        except (pd.errors.ParserError, pd.errors.EmptyDataError, OSError) as exc:
            logger.info(f"{sibling} не прочитан ({exc}) — его задачи считаются новыми")
    return frames


class LocalDatasetFiles:
    """Filesystem implementation of the application's dataset contract."""

    read_dataset_csv = staticmethod(read_dataset_csv)
    populate_record_paths = staticmethod(populate_record_paths)
    enrich_dataframe_paths = staticmethod(enrich_dataframe_paths)
    save_csv = staticmethod(save_csv)
    write_raw_csv = staticmethod(write_raw_csv)
    write_partition_csvs = staticmethod(write_partition_csvs)
    write_dataset_and_deleted = staticmethod(write_dataset_and_deleted)
    read_deleted_names = staticmethod(read_deleted_names)
    read_baseline_siblings = staticmethod(read_baseline_siblings)

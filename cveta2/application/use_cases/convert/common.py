"""Conversion preparation and dimension caching over supplied ports."""

from collections.abc import Sequence
from pathlib import Path

from loguru import logger

from cveta2.application.ports.conversion import ConversionFiles
from cveta2.domain.conversion import (
    ExportContext,
    _validate_export_rows,
    _validate_splits,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.output import preview_names


class _SizeCache:
    """Cache image dimensions, optionally reading only the first image.

    When *read_all* is False (default), reads the first image to determine
    the size and reuses it for all subsequent images.  When *read_all* is
    True, every image is opened individually.
    """

    def __init__(self, *, files: ConversionFiles, read_all: bool = False) -> None:
        self._files = files
        self._read_all = read_all
        self._cached: tuple[int, int] | None = None

    def get(self, img_path: Path) -> tuple[int, int]:
        """Return ``(width, height)`` for *img_path*."""
        if self._read_all:
            return self._files.image_size(img_path)
        if self._cached is None:
            self._cached = self._files.image_size(img_path)
            logger.debug(
                f"Размер изображений (по первому файлу): "
                f"{self._cached[0]}x{self._cached[1]}"
            )
        return self._cached


def prepare_export(  # noqa: PLR0913
    dataset: str | Path,
    output_dir: str | Path,
    *,
    image_dirs: Sequence[str | Path] | None,
    files: ConversionFiles,
    link_mode: str,
    label_start: int,
) -> ExportContext:
    """Load CSV, validate splits, build label map, and resolve images.

    *label_start* controls the first class ID (0 for YOLO, 1 for COCO).
    """
    csv_path = Path(dataset)
    out_dir = Path(output_dir)

    df = files.read_dataset_csv(csv_path, {"image_name", "instance_shape", "split"})
    df = df[df["instance_shape"].isin(["box", "none"])].copy()
    _validate_splits(df)
    _validate_export_rows(df, csv_path)
    if link_mode not in {"auto", "reflink", "hardlink", "symlink", "copy"}:
        raise Cveta2Error(f"Неизвестный link-mode: {link_mode!r}")

    box_df = df[df["instance_shape"] == "box"]
    label_map: dict[str, int] = {}
    if not box_df.empty:
        unique_labels = sorted(box_df["instance_label"].dropna().unique())
        label_map = {name: idx + label_start for idx, name in enumerate(unique_labels)}
    logger.info(f"Классов: {len(label_map)}, map: {label_map}")

    search_dirs = [Path(directory) for directory in image_dirs or ()]
    found, missing = files.resolve_images(set(df["image_name"].unique()), search_dirs)
    if missing:
        logger.warning(
            f"Не найдено {len(missing)} изображений: {preview_names(missing)}"
        )

    splits = sorted(df["split"].unique())
    logger.info(f"Сплиты: {splits}")

    return ExportContext(df, out_dir, link_mode, label_map, found, splits)

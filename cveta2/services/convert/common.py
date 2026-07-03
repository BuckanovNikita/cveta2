"""Shared helpers for CSV <-> YOLO/COCO conversion services."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pandas as pd
from loguru import logger

from cveta2.config import load_image_cache_config
from cveta2.exceptions import Cveta2Error
from cveta2.image_uploader import resolve_images
from cveta2.models import CSV_COLUMNS
from cveta2.services.output import read_dataset_csv

if TYPE_CHECKING:
    from collections.abc import Sequence

# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")


class PixelBox(NamedTuple):
    """Pixel-coordinate bounding box (top-left, bottom-right)."""

    x_tl: float
    y_tl: float
    x_br: float
    y_br: float


class YoloBox(NamedTuple):
    """YOLO normalized bounding box (center x, center y, width, height)."""

    xc: float
    yc: float
    w: float
    h: float


class CocoBox(NamedTuple):
    """COCO bounding box (top-left x, top-left y, width, height) in pixels."""

    x: float
    y: float
    w: float
    h: float


def _pixel_to_yolo(box: PixelBox, img_w: int, img_h: int) -> YoloBox:
    """Convert pixel bbox (top-left, bottom-right) to YOLO normalized (xc, yc, w, h)."""
    xc = ((box.x_tl + box.x_br) / 2.0) / img_w
    yc = ((box.y_tl + box.y_br) / 2.0) / img_h
    w = (box.x_br - box.x_tl) / img_w
    h = (box.y_br - box.y_tl) / img_h
    return YoloBox(xc, yc, w, h)


def _yolo_to_pixel(box: YoloBox, img_w: int, img_h: int) -> PixelBox:
    """Convert YOLO normalized (xc, yc, w, h) to pixel bbox (x_tl, y_tl, x_br, y_br)."""
    x_tl = (box.xc - box.w / 2) * img_w
    y_tl = (box.yc - box.h / 2) * img_h
    x_br = (box.xc + box.w / 2) * img_w
    y_br = (box.yc + box.h / 2) * img_h
    return PixelBox(x_tl, y_tl, x_br, y_br)


def _pixel_to_coco(box: PixelBox) -> CocoBox:
    """Convert pixel bbox (top-left, bottom-right) to COCO (x, y, w, h)."""
    return CocoBox(box.x_tl, box.y_tl, box.x_br - box.x_tl, box.y_br - box.y_tl)


# ---------------------------------------------------------------------------
# File placement
# ---------------------------------------------------------------------------


_reflink_fallback = {"warned": False}


def _copy_after_reflink_failure(src: Path, dst: Path, error: OSError) -> None:
    """Fall back to plain copy after a failed reflink attempt."""
    if not _reflink_fallback["warned"]:
        logger.warning(f"reflink недоступен ({error}): используется копирование")
        _reflink_fallback["warned"] = True
    dst.unlink(missing_ok=True)
    shutil.copy2(src, dst)


def _link_or_copy(src: Path, dst: Path, mode: str) -> None:
    """Place *src* at *dst* using the specified link mode.

    Modes: auto, reflink, hardlink, symlink, copy.
    """
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)

    if mode == "symlink":
        dst.symlink_to(src.resolve())
    elif mode == "hardlink":
        dst.hardlink_to(src)
    elif mode == "copy":
        shutil.copy2(src, dst)
    elif mode == "reflink":
        from reflink_copy import reflink  # noqa: PLC0415

        try:
            reflink(str(src), str(dst))
        except OSError as exc:
            _copy_after_reflink_failure(src, dst, exc)
    else:
        from reflink_copy import reflink_or_copy  # noqa: PLC0415

        try:
            reflink_or_copy(str(src), str(dst))
        except OSError as exc:
            _copy_after_reflink_failure(src, dst, exc)


# ---------------------------------------------------------------------------
# Image search / sizes
# ---------------------------------------------------------------------------


def _build_search_dirs(image_dir_args: Sequence[str | Path] | None) -> list[Path]:
    """Combine --image-dir args with all dirs from ImageCacheConfig."""
    dirs: list[Path] = [Path(d) for d in image_dir_args] if image_dir_args else []
    cache_cfg = load_image_cache_config()
    for cache_dir in cache_cfg.projects.values():
        if cache_dir not in dirs:
            dirs.append(cache_dir)
    return dirs


def _find_image_by_stem(
    stem: str,
    search_dirs: list[Path],
    subdirs: list[str] | None = None,
) -> Path | None:
    """Find an image file by stem across search dirs and common extensions.

    Searches flat dirs first, then one level of subdirs.
    """
    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        for ext in _IMAGE_EXTENSIONS:
            candidate = search_dir / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
        for sub in subdirs or []:
            sub_dir = search_dir / sub
            if not sub_dir.is_dir():
                continue
            for ext in _IMAGE_EXTENSIONS:
                candidate = sub_dir / f"{stem}{ext}"
                if candidate.is_file():
                    return candidate
    return None


def _get_image_size(img_path: Path) -> tuple[int, int]:
    """Get image dimensions using Pillow (lazy import)."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(img_path) as im:
        return im.size


class _SizeCache:
    """Cache image dimensions, optionally reading only the first image.

    When *read_all* is False (default), reads the first image to determine
    the size and reuses it for all subsequent images.  When *read_all* is
    True, every image is opened individually.
    """

    def __init__(self, *, read_all: bool = False) -> None:
        self._read_all = read_all
        self._cached: tuple[int, int] | None = None

    def get(self, img_path: Path) -> tuple[int, int]:
        """Return ``(width, height)`` for *img_path*."""
        if self._read_all:
            return _get_image_size(img_path)
        if self._cached is None:
            self._cached = _get_image_size(img_path)
            logger.debug(
                f"Размер изображений (по первому файлу): "
                f"{self._cached[0]}x{self._cached[1]}"
            )
        return self._cached


# ---------------------------------------------------------------------------
# CSV loading and split validation
# ---------------------------------------------------------------------------


def _validate_splits(df: pd.DataFrame) -> None:
    """Raise ``Cveta2Error`` if any images have no split value."""
    missing_split = df[df["split"].isna() | (df["split"] == "")]
    if not missing_split.empty:
        bad_images = sorted(missing_split["image_name"].unique()[:10])
        raise Cveta2Error(
            f"Ошибка: у {len(missing_split['image_name'].unique())} изображений "
            f"не задан split. Примеры: {', '.join(bad_images)}"
        )


class ExportContext(NamedTuple):
    """Shared state prepared by ``prepare_export``."""

    df: pd.DataFrame
    output_dir: Path
    link_mode: str
    label_map: dict[str, int]
    found: dict[str, Path]
    splits: list[str]


def prepare_export(
    dataset: str | Path,
    output_dir: str | Path,
    *,
    image_dirs: Sequence[str | Path] | None,
    link_mode: str,
    label_start: int = 0,
) -> ExportContext:
    """Load CSV, validate splits, build label map, and resolve images.

    *label_start* controls the first class ID (0 for YOLO, 1 for COCO).
    """
    csv_path = Path(dataset)
    out_dir = Path(output_dir)

    df = read_dataset_csv(csv_path, {"image_name", "instance_shape", "split"})
    df = df[df["instance_shape"].isin(["box", "none"])].copy()
    _validate_splits(df)

    box_df = df[df["instance_shape"] == "box"]
    label_map: dict[str, int] = {}
    if not box_df.empty:
        unique_labels = sorted(box_df["instance_label"].dropna().unique())
        label_map = {name: idx + label_start for idx, name in enumerate(unique_labels)}
    logger.info(f"Классов: {len(label_map)}, map: {label_map}")

    search_dirs = _build_search_dirs(image_dirs)
    found, missing = resolve_images(set(df["image_name"].unique()), search_dirs)
    if missing:
        logger.warning(f"Не найдено {len(missing)} изображений: {missing[:10]}")

    splits = sorted(df["split"].unique())
    logger.info(f"Сплиты: {splits}")

    out_dir.mkdir(parents=True, exist_ok=True)
    return ExportContext(df, out_dir, link_mode, label_map, found, splits)


# ---------------------------------------------------------------------------
# CSV row builders
# ---------------------------------------------------------------------------


def _make_csv_row_base(
    instance_shape: str,
    image_name: str,
    img_size: tuple[int, int],
    *,
    split: str | None,
    frame_id: int,
) -> dict[str, object]:
    """Build a CSV row dict with common fields shared by box/none rows."""
    row: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
    row.update(
        image_name=image_name,
        image_width=img_size[0],
        image_height=img_size[1],
        instance_shape=instance_shape,
        task_id=0,
        task_name="yolo",
        task_status="",
        task_updated_date="",
        created_by_username="",
        frame_id=frame_id,
        split=split,
        subset="",
        source="yolo",
        attributes=json.dumps({}, ensure_ascii=False),
    )
    return row


def _make_csv_row_box(  # noqa: PLR0913
    *,
    image_name: str,
    img_w: int,
    img_h: int,
    label: str,
    x_tl: float,
    y_tl: float,
    x_br: float,
    y_br: float,
    split: str | None,
    frame_id: int,
    annotation_id: int,
    confidence: float | None = None,
) -> dict[str, object]:
    """Build a CSV row dict for a box annotation."""
    row = _make_csv_row_base(
        "box",
        image_name,
        (img_w, img_h),
        split=split,
        frame_id=frame_id,
    )
    row.update(
        instance_label=label,
        bbox_x_tl=round(x_tl, 2),
        bbox_y_tl=round(y_tl, 2),
        bbox_x_br=round(x_br, 2),
        bbox_y_br=round(y_br, 2),
        occluded=False,
        z_order=0,
        rotation=0.0,
        annotation_id=annotation_id,
        confidence=confidence,
    )
    return row


def _make_csv_row_none(
    *,
    image_name: str,
    img_w: int,
    img_h: int,
    split: str | None,
    frame_id: int,
) -> dict[str, object]:
    """Build a CSV row dict for an image without annotations."""
    return _make_csv_row_base(
        "none",
        image_name,
        (img_w, img_h),
        split=split,
        frame_id=frame_id,
    )


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    """Write rows to CSV with proper column order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = (
        pd.DataFrame(rows, columns=list(CSV_COLUMNS))
        if rows
        else pd.DataFrame(columns=list(CSV_COLUMNS))
    )
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info(f"CSV сохранён: {path} ({len(df)} строк)")

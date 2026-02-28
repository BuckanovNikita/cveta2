"""Bidirectional conversion between cveta2 CSV and YOLO detection format."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pandas as pd
import yaml
from loguru import logger

from cveta2.commands._helpers import read_dataset_csv
from cveta2.config import load_image_cache_config
from cveta2.image_uploader import resolve_images
from cveta2.models import CSV_COLUMNS

if TYPE_CHECKING:
    import argparse

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


# ---------------------------------------------------------------------------
# File placement
# ---------------------------------------------------------------------------


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

        reflink(str(src), str(dst))
    else:
        # auto: try reflink, fall back to copy
        from reflink_copy import reflink_or_copy  # noqa: PLC0415

        reflink_or_copy(str(src), str(dst))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_search_dirs(image_dir_args: list[str] | None) -> list[Path]:
    """Combine --image-dir args with all dirs from ImageCacheConfig."""
    dirs: list[Path] = [Path(d) for d in image_dir_args] if image_dir_args else []
    cache_cfg = load_image_cache_config()
    for cache_dir in cache_cfg.projects.values():
        if cache_dir not in dirs:
            dirs.append(cache_dir)
    return dirs


def _parse_label_file(path: Path) -> list[list[float]]:
    """Read a YOLO label .txt file.

    Returns list of float lists. Each has 5 fields (class xc yc w h) or 6
    fields (class xc yc w h conf).
    """
    if not path.is_file():
        return []
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        rows.append([float(p) for p in parts])
    return rows


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


def _load_class_names_yaml(path: Path) -> dict[int, str]:
    """Load class names from a YAML file (supports {names: ...} or flat dict)."""
    if not path.is_file():
        sys.exit(f"Ошибка: файл имён классов не найден: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if isinstance(data, dict) and "names" in data:
        return {int(k): str(v) for k, v in data["names"].items()}
    if isinstance(data, dict):
        return {int(k): str(v) for k, v in data.items()}
    return {}


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


def _yolo_fields_to_row(  # noqa: PLR0913
    fields: list[float],
    class_names: dict[int, str],
    img_path: Path,
    img_w: int,
    img_h: int,
    split: str | None,
    frame_id: int,
    annotation_id: int,
) -> dict[str, object]:
    """Convert a parsed YOLO label line to a CSV row dict."""
    class_id = int(fields[0])
    yolo = YoloBox(fields[1], fields[2], fields[3], fields[4])
    conf = fields[5] if len(fields) >= 6 else None
    x_tl, y_tl, x_br, y_br = _yolo_to_pixel(yolo, img_w, img_h)
    label_name = class_names.get(class_id, f"class_{class_id}")
    return _make_csv_row_box(
        image_name=img_path.name,
        img_w=img_w,
        img_h=img_h,
        label=label_name,
        x_tl=x_tl,
        y_tl=y_tl,
        x_br=x_br,
        y_br=y_br,
        split=split,
        frame_id=frame_id,
        annotation_id=annotation_id,
        confidence=conf,
    )


# ---------------------------------------------------------------------------
# CSV -> YOLO
# ---------------------------------------------------------------------------


def _validate_splits(df: pd.DataFrame) -> None:
    """Exit with error if any images have no split value."""
    missing_split = df[df["split"].isna() | (df["split"] == "")]
    if not missing_split.empty:
        bad_images = sorted(missing_split["image_name"].unique()[:10])
        sys.exit(
            f"Ошибка: у {len(missing_split['image_name'].unique())} изображений "
            f"не задан split. Примеры: {', '.join(bad_images)}"
        )


def _write_box_labels(  # noqa: PLR0913
    box_df: pd.DataFrame,
    output_dir: Path,
    label_map: dict[str, int],
    found: dict[str, Path],
    link_mode: str,
    images_processed: set[str],
) -> None:
    """Write YOLO label files and place images for box annotations."""
    if box_df.empty:
        return
    for (raw_name, raw_split), group in box_df.groupby(["image_name", "split"]):
        name_s, split_s = str(raw_name), str(raw_split)

        if name_s in found and name_s not in images_processed:
            dst = output_dir / "images" / split_s / name_s
            _link_or_copy(found[name_s], dst, link_mode)
            images_processed.add(name_s)

        img_w = int(group.iloc[0]["image_width"])
        img_h = int(group.iloc[0]["image_height"])
        stem = Path(name_s).stem
        label_path = output_dir / "labels" / split_s / f"{stem}.txt"

        lines: list[str] = []
        for _, row in group.iterrows():
            class_id = label_map[row["instance_label"]]
            yolo = _pixel_to_yolo(
                PixelBox(
                    row["bbox_x_tl"],
                    row["bbox_y_tl"],
                    row["bbox_x_br"],
                    row["bbox_y_br"],
                ),
                img_w,
                img_h,
            )
            lines.append(
                f"{class_id} {yolo.xc:.6f} {yolo.yc:.6f} {yolo.w:.6f} {yolo.h:.6f}"
            )
        label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_none_labels(
    none_df: pd.DataFrame,
    output_dir: Path,
    found: dict[str, Path],
    link_mode: str,
    images_processed: set[str],
) -> None:
    """Write empty label files and place images for none-shape rows."""
    if none_df.empty:
        return
    for _, row in none_df.iterrows():
        image_name = str(row["image_name"])
        split = str(row["split"])

        if image_name in found and image_name not in images_processed:
            dst = output_dir / "images" / split / image_name
            _link_or_copy(found[image_name], dst, link_mode)
            images_processed.add(image_name)

        label_path = output_dir / "labels" / split / f"{Path(image_name).stem}.txt"
        if not label_path.exists():
            label_path.write_text("", encoding="utf-8")


def _write_dataset_yaml(
    output_dir: Path,
    splits: list[str],
    label_map: dict[str, int],
) -> None:
    """Write ultralytics dataset.yaml."""
    names_dict = {v: k for k, v in label_map.items()}
    yaml_data: dict[str, object] = {"path": str(output_dir.resolve())}
    for split_name in ("train", "val", "test"):
        if split_name in splits:
            yaml_data[split_name] = f"images/{split_name}"
    yaml_data["names"] = names_dict

    yaml_path = output_dir / "dataset.yaml"
    with yaml_path.open("w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=False)


def _convert_to_yolo(args: argparse.Namespace) -> None:
    """Convert cveta2 dataset.csv to YOLO detection format."""
    csv_path = Path(args.dataset)
    output_dir = Path(args.output)
    link_mode: str = args.link_mode or "auto"

    df = read_dataset_csv(csv_path, {"image_name", "instance_shape", "split"})
    df = df[df["instance_shape"].isin(["box", "none"])].copy()
    _validate_splits(df)

    box_df = df[df["instance_shape"] == "box"].copy()
    none_df = df[df["instance_shape"] == "none"].copy()

    label_map: dict[str, int] = {}
    if not box_df.empty:
        unique_labels = sorted(box_df["instance_label"].dropna().unique())
        label_map = {name: idx for idx, name in enumerate(unique_labels)}
    logger.info(f"Классов: {len(label_map)}, map: {label_map}")

    search_dirs = _build_search_dirs(getattr(args, "image_dir", None))
    found, missing = resolve_images(set(df["image_name"].unique()), search_dirs)
    if missing:
        logger.warning(f"Не найдено {len(missing)} изображений: {missing[:10]}")

    splits = sorted(df["split"].unique())
    logger.info(f"Сплиты: {splits}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for split in splits:
        (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    images_processed: set[str] = set()
    _write_box_labels(box_df, output_dir, label_map, found, link_mode, images_processed)
    _write_none_labels(none_df, output_dir, found, link_mode, images_processed)
    _write_dataset_yaml(output_dir, splits, label_map)

    logger.info(
        f"Готово: {len(images_processed)} изображений, "
        f"{len(label_map)} классов -> {output_dir}"
    )


# ---------------------------------------------------------------------------
# YOLO -> CSV
# ---------------------------------------------------------------------------


def _convert_from_yolo(args: argparse.Namespace) -> None:
    """Convert YOLO detection format to cveta2 CSV."""
    input_dir = Path(args.input)
    output_path = Path(args.output)
    names_file = Path(args.names_file) if args.names_file else None

    yaml_path = input_dir / "dataset.yaml"
    if yaml_path.is_file():
        logger.info(f"Режим датасета: найден {yaml_path}")
        _from_yolo_dataset(input_dir, yaml_path, output_path, args)
    else:
        logger.info("Режим предсказаний: dataset.yaml не найден")
        _from_yolo_predictions(input_dir, output_path, names_file, args)


def _from_yolo_dataset(
    input_dir: Path,
    yaml_path: Path,
    output_path: Path,
    args: argparse.Namespace,
) -> None:
    """Convert YOLO dataset (with dataset.yaml) to CSV."""
    with yaml_path.open("r", encoding="utf-8") as f:
        ds_config = yaml.safe_load(f)

    class_names: dict[int, str] = {
        int(k): str(v) for k, v in ds_config.get("names", {}).items()
    }
    if not class_names:
        sys.exit(f"Ошибка: в {yaml_path} не найдены имена классов (names)")

    read_all = getattr(args, "read_all_sizes", False)
    sizes = _SizeCache(read_all=read_all)

    rows: list[dict[str, object]] = []
    frame_id = 0
    annotation_id = 1

    for split_key in ("train", "val", "test"):
        split_val = ds_config.get(split_key)
        if not split_val:
            continue

        images_dir = input_dir / str(split_val)
        labels_dir = input_dir / str(split_val).replace("images", "labels")

        if not images_dir.is_dir():
            logger.warning(f"Директория изображений не найдена: {images_dir}")
            continue

        for img_path in sorted(images_dir.iterdir()):
            if img_path.suffix.lower() not in _IMAGE_EXTENSIONS:
                continue

            img_w, img_h = sizes.get(img_path)
            labels = _parse_label_file(labels_dir / f"{img_path.stem}.txt")

            if not labels:
                rows.append(
                    _make_csv_row_none(
                        image_name=img_path.name,
                        img_w=img_w,
                        img_h=img_h,
                        split=split_key,
                        frame_id=frame_id,
                    )
                )
            else:
                for fields in labels:
                    rows.append(
                        _yolo_fields_to_row(
                            fields,
                            class_names,
                            img_path,
                            img_w,
                            img_h,
                            split_key,
                            frame_id,
                            annotation_id,
                        )
                    )
                    annotation_id += 1

            frame_id += 1

    _write_csv(rows, output_path)


def _from_yolo_predictions(
    input_dir: Path,
    output_path: Path,
    names_file: Path | None,
    args: argparse.Namespace,
) -> None:
    """Convert bare YOLO prediction .txt files to CSV."""
    class_names = _load_class_names_yaml(names_file) if names_file else {}
    search_dirs = _build_search_dirs(getattr(args, "image_dir", None))

    label_files = sorted(input_dir.glob("**/*.txt"))
    if not label_files:
        sys.exit(f"Ошибка: не найдено .txt файлов в {input_dir}")

    read_all = getattr(args, "read_all_sizes", False)
    sizes = _SizeCache(read_all=read_all)

    rows: list[dict[str, object]] = []
    frame_id = 0
    annotation_id = 1
    missing_images: list[str] = []

    for label_path in label_files:
        labels = _parse_label_file(label_path)
        if not labels:
            continue

        img_path = _find_image_by_stem(
            label_path.stem,
            [input_dir, *search_dirs],
            subdirs=["images"],
        )
        if img_path is None:
            missing_images.append(label_path.stem)
            continue

        img_w, img_h = sizes.get(img_path)
        for fields in labels:
            rows.append(
                _yolo_fields_to_row(
                    fields,
                    class_names,
                    img_path,
                    img_w,
                    img_h,
                    None,
                    frame_id,
                    annotation_id,
                )
            )
            annotation_id += 1
        frame_id += 1

    if missing_images:
        logger.warning(
            f"Не найдены изображения для {len(missing_images)} файлов: "
            f"{missing_images[:10]}"
        )

    _write_csv(rows, output_path)


# ---------------------------------------------------------------------------
# CSV row builders
# ---------------------------------------------------------------------------


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
    row: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
    row.update(
        image_name=image_name,
        image_width=img_w,
        image_height=img_h,
        instance_shape="box",
        instance_label=label,
        bbox_x_tl=round(x_tl, 2),
        bbox_y_tl=round(y_tl, 2),
        bbox_x_br=round(x_br, 2),
        bbox_y_br=round(y_br, 2),
        task_id=0,
        task_name="yolo",
        task_status="",
        task_updated_date="",
        created_by_username="",
        frame_id=frame_id,
        split=split,
        subset="",
        occluded=False,
        z_order=0,
        rotation=0.0,
        source="yolo",
        annotation_id=annotation_id,
        confidence=confidence,
        attributes=json.dumps({}, ensure_ascii=False),
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
    row: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
    row.update(
        image_name=image_name,
        image_width=img_w,
        image_height=img_h,
        instance_shape="none",
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_convert(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate conversion direction."""
    if getattr(args, "to_yolo", False):
        _convert_to_yolo(args)
    elif getattr(args, "from_yolo", False):
        _convert_from_yolo(args)
    else:
        sys.exit("Ошибка: укажите --to-yolo или --from-yolo")

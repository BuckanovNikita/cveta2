"""CSV <-> YOLO detection format conversion services."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from loguru import logger

from cveta2.exceptions import Cveta2Error
from cveta2.services.convert.common import (
    _IMAGE_EXTENSIONS,
    PixelBox,
    YoloBox,
    _build_search_dirs,
    _find_image_by_stem,
    _link_or_copy,
    _make_csv_row_box,
    _make_csv_row_none,
    _pixel_to_yolo,
    _require_positive_dimensions,
    _SizeCache,
    _write_csv,
    _yolo_to_pixel,
    prepare_export,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pandas as pd


# ---------------------------------------------------------------------------
# CSV -> YOLO
# ---------------------------------------------------------------------------


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
        _require_positive_dimensions(img_w, img_h, name_s)
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


def convert_to_yolo(
    dataset: str | Path,
    output_dir: str | Path,
    *,
    image_dirs: Sequence[str | Path] | None = None,
    link_mode: Literal["auto", "reflink", "hardlink", "symlink", "copy"] = "auto",
) -> Path:
    """Convert cveta2 dataset.csv to YOLO detection format.

    Returns the output directory path.
    """
    ctx = prepare_export(
        dataset,
        output_dir,
        image_dirs=image_dirs,
        link_mode=link_mode,
        label_start=0,
    )

    for split in ctx.splits:
        (ctx.output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (ctx.output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    box_df = ctx.df[ctx.df["instance_shape"] == "box"].copy()
    none_df = ctx.df[ctx.df["instance_shape"] == "none"].copy()

    images_processed: set[str] = set()
    _write_box_labels(
        box_df,
        ctx.output_dir,
        ctx.label_map,
        ctx.found,
        ctx.link_mode,
        images_processed,
    )
    _write_none_labels(
        none_df,
        ctx.output_dir,
        ctx.found,
        ctx.link_mode,
        images_processed,
    )
    _write_dataset_yaml(ctx.output_dir, ctx.splits, ctx.label_map)

    logger.info(
        f"Готово: {len(images_processed)} изображений, {len(box_df)} боксов, "
        f"{len(ctx.label_map)} классов -> {ctx.output_dir}"
    )
    return ctx.output_dir


# ---------------------------------------------------------------------------
# YOLO -> CSV
# ---------------------------------------------------------------------------


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


def _load_class_names_yaml(path: Path) -> dict[int, str]:
    """Load class names from a YAML file (supports {names: ...} or flat dict)."""
    if not path.is_file():
        raise Cveta2Error(f"Ошибка: файл имён классов не найден: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if isinstance(data, dict) and "names" in data:
        return {int(k): str(v) for k, v in data["names"].items()}
    if isinstance(data, dict):
        return {int(k): str(v) for k, v in data.items()}
    return {}


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


def _from_yolo_dataset(
    input_dir: Path,
    yaml_path: Path,
    output_path: Path,
    *,
    read_all_sizes: bool,
) -> None:
    """Convert YOLO dataset (with dataset.yaml) to CSV."""
    with yaml_path.open("r", encoding="utf-8") as f:
        ds_config = yaml.safe_load(f)

    class_names: dict[int, str] = {
        int(k): str(v) for k, v in ds_config.get("names", {}).items()
    }
    if not class_names:
        raise Cveta2Error(f"Ошибка: в {yaml_path} не найдены имена классов (names)")

    sizes = _SizeCache(read_all=read_all_sizes)

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
            _require_positive_dimensions(img_w, img_h, img_path.name)
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
    *,
    image_dirs: Sequence[str | Path] | None,
    read_all_sizes: bool,
) -> None:
    """Convert bare YOLO prediction .txt files to CSV."""
    class_names = _load_class_names_yaml(names_file) if names_file else {}
    search_dirs = _build_search_dirs(image_dirs)

    label_files = sorted(input_dir.glob("**/*.txt"))
    if not label_files:
        raise Cveta2Error(f"Ошибка: не найдено .txt файлов в {input_dir}")

    sizes = _SizeCache(read_all=read_all_sizes)

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
        _require_positive_dimensions(img_w, img_h, img_path.name)
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


def convert_from_yolo(
    input_dir: str | Path,
    output_csv: str | Path,
    *,
    names_file: str | Path | None = None,
    read_all_sizes: bool = False,
    image_dirs: Sequence[str | Path] | None = None,
) -> Path:
    """Convert YOLO detection format to cveta2 CSV.

    Returns the output CSV path.
    """
    in_dir = Path(input_dir)
    output_path = Path(output_csv)
    names_path = Path(names_file) if names_file else None

    yaml_path = in_dir / "dataset.yaml"
    if yaml_path.is_file():
        logger.info(f"Режим датасета: найден {yaml_path}")
        _from_yolo_dataset(
            in_dir,
            yaml_path,
            output_path,
            read_all_sizes=read_all_sizes,
        )
    else:
        logger.info("Режим предсказаний: dataset.yaml не найден")
        _from_yolo_predictions(
            in_dir,
            output_path,
            names_path,
            image_dirs=image_dirs,
            read_all_sizes=read_all_sizes,
        )
    return output_path

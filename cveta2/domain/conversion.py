"""Pure conversion transforms, external-value validation, and output formatting."""

import json
import math
from pathlib import Path
from typing import NamedTuple, TypedDict

import pandas as pd
import yaml
from loguru import logger

from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import CSV_COLUMNS
from cveta2.domain.output import preview_names

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")
_EMPTY_ATTRIBUTES = json.dumps({}, ensure_ascii=False)
_YOLO_BOX_FIELDS = 5
_YOLO_CONF_FIELDS = 6


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


def _require_positive_dimensions(img_w: int, img_h: int, image_name: str) -> None:
    """Raise ``Cveta2Error`` when an image dimension is missing or non-positive."""
    if img_w <= 0 or img_h <= 0:
        raise Cveta2Error(
            f"Ошибка: некорректный размер изображения {image_name!r} "
            f"({img_w}x{img_h}). Ширина и высота должны быть положительными."
        )


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


def _validate_splits(df: pd.DataFrame) -> None:
    """Raise ``Cveta2Error`` if any images have no split value."""
    missing_split = df[df["split"].isna() | (df["split"] == "")]
    if not missing_split.empty:
        bad_images = sorted(missing_split["image_name"].unique())
        raise Cveta2Error(
            f"Ошибка: у {len(bad_images)} изображений "
            f"не задан split. Примеры: {preview_names(bad_images)}"
        )

    unsupported = df[~df["split"].isin(["train", "val", "test"])]
    if not unsupported.empty:
        values = sorted(str(value) for value in unsupported["split"].unique())
        names = sorted(str(value) for value in unsupported["image_name"].unique())
        raise Cveta2Error(
            f"Ошибка: недопустимый split {values}: {preview_names(names)}. "
            "Допустимы train, val, test."
        )


def _validate_export_rows(df: pd.DataFrame, csv_path: Path) -> None:
    """Validate external row values before creating or pruning output."""
    boxes = df[df["instance_shape"] == "box"]
    required = {"image_width", "image_height"}
    if not boxes.empty:
        required |= {
            "instance_label",
            "bbox_x_tl",
            "bbox_y_tl",
            "bbox_x_br",
            "bbox_y_br",
        }
    missing = required - set(df.columns)
    if missing:
        raise Cveta2Error(
            f"Ошибка: в {csv_path} отсутствуют столбцы: {sorted(missing)}"
        )
    for _, row in df.iterrows():
        name = row["image_name"]
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name in {".", ".."}
            or "\\" in name
            or "\x00" in name
        ):
            raise Cveta2Error(
                f"Ошибка: некорректное имя изображения в {csv_path}: {name!r}"
            )
        try:
            dimensions = [
                float(row[column]) for column in ("image_width", "image_height")
            ]
        except (ValueError, TypeError) as exc:
            raise Cveta2Error(
                f"Ошибка: некорректный размер {name!r} в {csv_path}"
            ) from exc
        if any(
            not math.isfinite(value) or value <= 0 or not value.is_integer()
            for value in dimensions
        ):
            raise Cveta2Error(
                f"Ошибка: некорректный размер {name!r} "
                f"({dimensions[0]:g}x{dimensions[1]:g}) в {csv_path}"
            )
        if row["instance_shape"] == "box":
            _validate_export_box(row, csv_path)


def _validate_export_box(row: pd.Series, csv_path: Path) -> None:
    """Reject incomplete or nonfinite external box values."""
    name = row["image_name"]
    if not isinstance(row["instance_label"], str) or not row["instance_label"]:
        raise Cveta2Error(f"Ошибка: не задан класс {name!r} в {csv_path}")
    try:
        coords = [
            float(row[column])
            for column in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br")
        ]
    except (ValueError, TypeError) as exc:
        raise Cveta2Error(f"Ошибка: некорректный bbox {name!r} в {csv_path}") from exc
    if (
        any(not math.isfinite(value) for value in coords)
        or coords[2] <= coords[0]
        or coords[3] <= coords[1]
    ):
        raise Cveta2Error(f"Ошибка: некорректный bbox {name!r} в {csv_path}")


class ExportContext(NamedTuple):
    """Shared state prepared by ``prepare_export``."""

    df: pd.DataFrame
    output_dir: Path
    link_mode: str
    label_map: dict[str, int]
    found: dict[str, Path]
    splits: list[str]


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
        job_stage="",
        job_state="",
        task_updated_date="",
        created_by_username="",
        frame_id=frame_id,
        split=split,
        subset="",
        source="yolo",
        attributes=_EMPTY_ATTRIBUTES,
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


def _parse_label_text(text: str, path: Path) -> list[list[float]]:
    """Read a YOLO label .txt file.

    Returns list of float lists. Each has 5 fields (class xc yc w h) or 6
    fields (class xc yc w h conf). Longer lines — segmentation, OBB or
    keypoint labels — are kept as they are and later read as detection boxes
    from their first six fields; their count is reported as a warning.

    Short and non-numeric lines are skipped rather than aborting the whole
    conversion — a label set that went through other tooling may carry a
    header or a stray token — but the count is reported so the caller knows
    the result is incomplete.
    """
    rows: list[list[float]] = []
    skipped = 0
    extra_fields = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        parts = line.strip().split()
        if not parts:
            continue
        try:
            fields = [float(part) for part in parts]
            valid = (
                len(fields) >= _YOLO_BOX_FIELDS
                and all(math.isfinite(value) for value in fields)
                and fields[0] >= 0
                and fields[0].is_integer()
                and all(0 <= value <= 1 for value in fields[1:3])
                and all(0 < value <= 1 for value in fields[3:5])
                and (len(fields) < _YOLO_CONF_FIELDS or 0 <= fields[5] <= 1)
            )
        except ValueError:
            valid = False
        if not valid:
            skipped += 1
            logger.warning(
                f"Пропущена некорректная строка {path}:{line_number}: {line!r}"
            )
            continue
        rows.append(fields)
        if len(parts) > _YOLO_CONF_FIELDS:
            extra_fields += 1
    if skipped:
        logger.warning(f"Пропущено нечитаемых строк в {path}: {skipped}")
    if extra_fields:
        logger.warning(
            f"Строк с полями сверх {_YOLO_CONF_FIELDS} (сегментация/OBB/keypoints?) "
            f"в {path}: {extra_fields}; учтены только class xc yc w h [conf]"
        )
    return rows


def _normalize_class_names(names: object, source: Path) -> dict[int, str]:
    """Turn the ``names`` value of a YOLO yaml into ``{class_id: name}``.

    Ultralytics accepts both ``names: {0: cat, 1: dog}`` and the older
    ``names: [cat, dog]``, where the position is the class id.
    """
    if isinstance(names, list):
        entries = dict(enumerate(names))
    elif isinstance(names, dict):
        entries = names
    else:
        raise Cveta2Error(f"Ошибка: names в {source} должен быть списком или словарём")
    result: dict[int, str] = {}
    for key, name in entries.items():
        if isinstance(key, bool) or not (
            isinstance(key, int)
            or (isinstance(key, str) and key.isascii() and key.isdecimal())
        ):
            raise Cveta2Error(f"Ошибка: некорректный ID класса {key!r} в {source}")
        class_id = int(key)
        if (
            class_id < 0
            or class_id in result
            or not isinstance(name, str)
            or not name.strip()
            or name in result.values()
        ):
            raise Cveta2Error(
                f"Ошибка: некорректный names в {source}: {key!r}: {name!r}"
            )
        result[class_id] = name
    return result


def _yolo_fields_to_row(  # noqa: PLR0913, PLR0917
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
    conf = fields[5] if len(fields) >= _YOLO_CONF_FIELDS else None
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


def _label_path_for_image(img_path: Path) -> Path:
    """Return the conventional YOLO label path for an image path."""
    parts = list(img_path.parts)
    image_indexes = [index for index, part in enumerate(parts) if part == "images"]
    if image_indexes:
        parts[image_indexes[-1]] = "labels"
        return Path(*parts).with_suffix(".txt")
    return img_path.with_suffix(".txt")


def yolo_label_text(group: pd.DataFrame, label_map: dict[str, int], name_s: str) -> str:
    """Format one image's boxes as deterministic six-decimal YOLO labels."""
    img_w = int(group.iloc[0]["image_width"])
    img_h = int(group.iloc[0]["image_height"])
    _require_positive_dimensions(img_w, img_h, name_s)
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
    return "\n".join(lines) + "\n"


class _YamlDumpOptions(TypedDict):
    """Serializer knobs for ``dataset.yaml``; ``yaml.safe_load`` ignores both."""

    default_flow_style: bool
    allow_unicode: bool


_YAML_DUMP: _YamlDumpOptions = {"default_flow_style": False, "allow_unicode": False}


def yolo_dataset_text(
    output_dir: Path, splits: list[str], label_map: dict[str, int]
) -> str:
    """Format ultralytics metadata from a resolved output root and split values."""
    names_dict = {v: k for k, v in label_map.items()}
    yaml_data: dict[str, object] = {"path": str(output_dir)}
    for split_name in ("train", "val", "test"):
        if split_name in splits:
            yaml_data[split_name] = f"images/{split_name}"
    yaml_data["names"] = names_dict
    return yaml.dump(yaml_data, **_YAML_DUMP)


def coco_split_data(
    split_df: pd.DataFrame, label_map: dict[str, int]
) -> dict[str, list[dict[str, object]]]:
    """Build deterministic COCO image, annotation and category records."""
    images_list: list[dict[str, object]] = []
    image_id_map: dict[str, int] = {}
    first_rows = split_df.groupby("image_name").first()
    for img_id, image_name in enumerate(
        sorted(split_df["image_name"].unique()), start=1
    ):
        name_s = str(image_name)
        first_row = first_rows.loc[image_name]
        image_id_map[name_s] = img_id
        images_list.append(
            {
                "id": img_id,
                "file_name": name_s,
                "width": int(first_row["image_width"]),
                "height": int(first_row["image_height"]),
            }
        )

    annotations_list: list[dict[str, object]] = []
    split_boxes = split_df[split_df["instance_shape"] == "box"]
    ann_id = 0
    for _, row in split_boxes.iterrows():
        name_s = str(row["image_name"])
        if name_s not in image_id_map:
            continue
        coco = _pixel_to_coco(
            PixelBox(
                row["bbox_x_tl"], row["bbox_y_tl"], row["bbox_x_br"], row["bbox_y_br"]
            )
        )
        ann_id += 1
        annotations_list.append(
            {
                "id": ann_id,
                "image_id": image_id_map[name_s],
                "category_id": label_map[row["instance_label"]],
                "bbox": [
                    round(coco.x, 2),
                    round(coco.y, 2),
                    round(coco.w, 2),
                    round(coco.h, 2),
                ],
                "area": round(coco.w * coco.h, 2),
                "iscrowd": 0,
            }
        )

    categories_list = [
        {"id": cat_id, "name": name, "supercategory": "none"}
        for name, cat_id in sorted(label_map.items(), key=lambda x: x[1])
    ]

    return {
        "images": images_list,
        "annotations": annotations_list,
        "categories": categories_list,
    }


class _JsonDumpOptions(TypedDict):
    """Serializer knobs for the COCO JSON; ``json.load`` ignores both."""

    ensure_ascii: bool
    indent: int


_JSON_DUMP: _JsonDumpOptions = {"ensure_ascii": False, "indent": 2}


def coco_metadata_text(data: dict[str, list[dict[str, object]]]) -> str:
    """Serialize COCO metadata with Unicode preserved and existing indentation."""
    return json.dumps(data, **_JSON_DUMP)

"""CSV -> COCO detection format conversion service."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, TypedDict

from loguru import logger

from cveta2.services.convert.common import (
    PixelBox,
    _link_or_copy,
    _pixel_to_coco,
    prepare_export,
)
from cveta2.services.output import write_text_utf8

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import pandas as pd


class _JsonDumpOptions(TypedDict):
    """Serializer knobs for the COCO JSON; ``json.load`` ignores both."""

    ensure_ascii: bool
    indent: int


_JSON_DUMP: _JsonDumpOptions = {"ensure_ascii": False, "indent": 2}


def _write_coco_split(
    split_df: pd.DataFrame,
    split_dir: Path,
    label_map: dict[str, int],
    found: dict[str, Path],
    link_mode: str,
) -> None:
    """Write COCO JSON and place images for a single split."""
    images_list: list[dict[str, object]] = []
    image_id_map: dict[str, int] = {}
    first_rows = split_df.groupby("image_name").first()
    for img_id, image_name in enumerate(
        sorted(split_df["image_name"].unique()), start=1
    ):
        name_s = str(image_name)
        if name_s in found:
            _link_or_copy(found[name_s], split_dir / name_s, link_mode)

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

    coco_json = {
        "images": images_list,
        "annotations": annotations_list,
        "categories": categories_list,
    }
    json_path = split_dir / "_annotations.coco.json"
    write_text_utf8(json_path, json.dumps(coco_json, **_JSON_DUMP))

    logger.info(
        f"Split {split_dir.name}: {len(images_list)} изображений, "
        f"{len(annotations_list)} аннотаций -> {json_path}"
    )


def convert_to_coco(
    dataset: str | Path,
    output_dir: str | Path,
    *,
    image_dirs: Sequence[str | Path] | None = None,
    link_mode: Literal["auto", "reflink", "hardlink", "symlink", "copy"] = "auto",
) -> Path:
    """Convert cveta2 dataset.csv to COCO detection format (rfdetr-compatible).

    Returns the output directory path.
    """
    ctx = prepare_export(
        dataset,
        output_dir,
        image_dirs=image_dirs,
        link_mode=link_mode,
        label_start=1,
    )

    split_dir_map: dict[str, str] = {"val": "valid"}
    for split in ctx.splits:
        dir_name = split_dir_map.get(split, split)
        split_dir = ctx.output_dir / dir_name
        split_dir.mkdir(parents=True, exist_ok=True)
        _write_coco_split(
            ctx.df[ctx.df["split"] == split],
            split_dir,
            ctx.label_map,
            ctx.found,
            ctx.link_mode,
        )

    logger.info(f"Готово: COCO датасет сохранён в {ctx.output_dir}")
    return ctx.output_dir

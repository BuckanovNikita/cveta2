"""CSV -> COCO detection format conversion service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict

from loguru import logger

from cveta2.exceptions import Cveta2Error
from cveta2.services.convert.common import (
    ExportContext,
    PixelBox,
    _link_or_copy,
    _pixel_to_coco,
    prepare_export,
)
from cveta2.services.output import read_text_utf8, write_text_utf8

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def _coco_owned_paths(ctx: ExportContext) -> set[Path]:
    """Validate prior export metadata and destination paths before any writes."""
    owned: set[Path] = set()
    if any(
        path.is_symlink()
        for path in (ctx.output_dir.absolute(), *ctx.output_dir.absolute().parents)
    ):
        raise Cveta2Error(f"Ошибка: каталог COCO является ссылкой: {ctx.output_dir}")
    for split in ("train", "valid", "test"):
        directory = ctx.output_dir / split
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise Cveta2Error(f"Ошибка: небезопасный каталог COCO: {directory}")
        metadata = directory / "_annotations.coco.json"
        if metadata.is_symlink():
            raise Cveta2Error(f"Ошибка: небезопасные метаданные COCO: {metadata}")
        if not metadata.exists():
            continue
        owned.update(_owned_split_files(directory, metadata))
    for name, split in ctx.df[["image_name", "split"]].itertuples(
        index=False, name=None
    ):
        if name == "_annotations.coco.json":
            raise Cveta2Error(
                f"Ошибка: имя изображения совпадает с метаданными COCO: {name}"
            )
        destination = ctx.output_dir / ("valid" if split == "val" else split) / name
        if (
            destination.exists() or destination.is_symlink()
        ) and destination not in owned:
            raise Cveta2Error(
                f"Ошибка: путь не принадлежит предыдущему экспорту COCO: {destination}"
            )
    return owned


def _owned_split_files(directory: Path, metadata: Path) -> set[Path]:
    """Read and confine the image inventory of one previous split."""
    try:
        data = json.loads(read_text_utf8(metadata))
    except (json.JSONDecodeError, UnicodeError, OSError) as exc:
        raise Cveta2Error(
            f"Ошибка: не удалось прочитать метаданные COCO {metadata}: {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("images"), list):
        raise Cveta2Error(f"Ошибка: неоднозначные метаданные COCO: {metadata}")
    owned: set[Path] = {metadata}
    names: set[str] = set()
    for image in data["images"]:
        name = image.get("file_name") if isinstance(image, dict) else None
        if (
            not isinstance(name, str)
            or not name
            or name in {".", "..", "_annotations.coco.json"}
            or Path(name).name != name
            or "\\" in name
            or "\x00" in name
            or name in names
        ):
            raise Cveta2Error(f"Ошибка: небезопасное имя в {metadata}: {name!r}")
        names.add(name)
        path = directory / name
        if path.exists() and not path.is_file():
            raise Cveta2Error(f"Ошибка: небезопасный путь COCO: {path}")
        owned.add(path)
    return owned


def _prune_coco_output(ctx: ExportContext, owned: set[Path]) -> None:
    """Remove only previously declared files absent from this export."""
    expected: set[Path] = set()
    for name, split in ctx.df[["image_name", "split"]].itertuples(
        index=False, name=None
    ):
        directory = ctx.output_dir / ("valid" if split == "val" else split)
        expected.add(directory / name)
        expected.add(directory / "_annotations.coco.json")
    for path in owned - expected:
        path.unlink(missing_ok=True)
    for directory in {path.parent for path in owned}:
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


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

    owned = _coco_owned_paths(ctx)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
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

    _prune_coco_output(ctx, owned)
    logger.info(f"Готово: COCO датасет сохранён в {ctx.output_dir}")
    return ctx.output_dir

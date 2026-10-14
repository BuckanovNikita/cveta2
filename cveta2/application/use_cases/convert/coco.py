"""COCO conversion orchestration with explicit filesystem effects."""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pandas as pd
from loguru import logger

from cveta2.application.ports.conversion import ConversionFiles
from cveta2.application.use_cases.convert.common import prepare_export
from cveta2.domain.conversion import coco_metadata_text, coco_split_data


def _write_coco_split(  # noqa: PLR0913, PLR0917
    split_df: pd.DataFrame,
    split_dir: Path,
    label_map: dict[str, int],
    found: dict[str, Path],
    link_mode: str,
    files: ConversionFiles,
) -> None:
    """Write COCO JSON and place images for a single split."""
    for name in sorted(split_df["image_name"].unique()):
        name_s = str(name)
        if name_s in found:
            files.materialize_image(found[name_s], split_dir / name_s, link_mode)
    coco_json = coco_split_data(split_df, label_map)
    json_path = split_dir / "_annotations.coco.json"
    files.write_output_text(json_path, coco_metadata_text(coco_json))

    logger.info(
        f"Split {split_dir.name}: {len(coco_json['images'])} изображений, "
        f"{len(coco_json['annotations'])} аннотаций -> {json_path}"
    )


def convert_to_coco(
    dataset: str | Path,
    output_dir: str | Path,
    *,
    image_dirs: Sequence[str | Path] | None = None,
    files: ConversionFiles,
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
        files=files,
    )

    owned = files.coco_owned_paths(ctx)
    files.prepare_coco_output(ctx.output_dir)
    split_dir_map: dict[str, str] = {"val": "valid"}
    for split in ctx.splits:
        dir_name = split_dir_map.get(split, split)
        split_dir = ctx.output_dir / dir_name
        files.prepare_coco_split(split_dir)
        _write_coco_split(
            ctx.df[ctx.df["split"] == split],
            split_dir,
            ctx.label_map,
            ctx.found,
            ctx.link_mode,
            files,
        )

    files.prune_coco_output(ctx, owned)
    logger.info(f"Готово: COCO датасет сохранён в {ctx.output_dir}")
    return ctx.output_dir

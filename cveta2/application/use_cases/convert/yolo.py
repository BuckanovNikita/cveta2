"""YOLO conversion orchestration with explicit filesystem effects."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd
from loguru import logger

from cveta2.application.ports.conversion import ConversionFiles
from cveta2.application.use_cases.convert.common import _SizeCache, prepare_export
from cveta2.domain.conversion import (
    UnreadableLabelError,
    YoloLabels,
    _label_path_for_image,
    _make_csv_row_base,
    _normalize_class_names,
    _parse_label_text,
    _require_positive_dimensions,
    _yolo_fields_to_row,
    yolo_dataset_text,
    yolo_label_text,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.output import preview_names


@dataclass
class _BoxAdjustments:
    """Clipped and dropped box counts of one export, with the affected image names."""

    clipped: int = 0
    dropped: int = 0
    clipped_images: list[str] = field(default_factory=list)
    dropped_images: list[str] = field(default_factory=list)

    def record(self, image_name: str, labels: YoloLabels) -> None:
        """Add one image's counts."""
        self.clipped += labels.clipped
        self.dropped += labels.dropped
        if labels.clipped:
            self.clipped_images.append(image_name)
        if labels.dropped:
            self.dropped_images.append(image_name)

    def warn(self) -> None:
        """Summarize clipped and dropped boxes, each in one warning line."""
        if self.clipped:
            logger.warning(
                f"Боксы, выходящие за границы изображения, обрезаны по ним: {self.clipped} "
                f"({preview_names(self.clipped_images)})"
            )
        if self.dropped:
            logger.warning(
                f"Пропущены боксы с нулевой шириной или высотой после обрезки или округления: {self.dropped} "
                f"({preview_names(self.dropped_images)})"
            )


def _write_box_labels(  # noqa: PLR0913, PLR0917
    box_df: pd.DataFrame,
    output_dir: Path,
    label_map: dict[str, int],
    found: dict[str, Path],
    link_mode: str,
    images_processed: set[str],
    files: ConversionFiles,
) -> _BoxAdjustments:
    """Write YOLO label files and place images for box annotations."""
    adjustments = _BoxAdjustments()
    if box_df.empty:
        return adjustments
    for (raw_name, raw_split), group in box_df.groupby(["image_name", "split"]):
        name_s, split_s = str(raw_name), str(raw_split)

        if name_s in found and name_s not in images_processed:
            dst = output_dir / "images" / split_s / name_s
            files.materialize_image(found[name_s], dst, link_mode)
            images_processed.add(name_s)

        label_path = output_dir / "labels" / split_s / f"{Path(name_s).stem}.txt"
        labels = yolo_label_text(group, label_map, name_s)
        files.write_output_text(label_path, labels.text)
        adjustments.record(name_s, labels)
    return adjustments


def _write_none_labels(  # noqa: PLR0913
    none_df: pd.DataFrame,
    output_dir: Path,
    found: dict[str, Path],
    link_mode: str,
    images_processed: set[str],
    *,
    box_images: set[tuple[str, str]],
    files: ConversionFiles,
) -> None:
    """Write empty label files and place images for none-shape rows."""
    if none_df.empty:
        return
    for _, row in none_df.iterrows():
        image_name = str(row["image_name"])
        split = str(row["split"])

        if image_name in found and image_name not in images_processed:
            dst = output_dir / "images" / split / image_name
            files.materialize_image(found[image_name], dst, link_mode)
            images_processed.add(image_name)

        label_path = output_dir / "labels" / split / f"{Path(image_name).stem}.txt"
        if (image_name, split) not in box_images:
            files.write_output_text(label_path, "")


def _write_dataset_yaml(
    output_dir: Path,
    splits: list[str],
    label_map: dict[str, int],
    files: ConversionFiles,
) -> None:
    """Write ultralytics dataset.yaml."""
    files.write_output_text(
        output_dir / "dataset.yaml",
        yolo_dataset_text(files.resolved_output_dir(output_dir), splits, label_map),
    )


def convert_to_yolo(
    dataset: str | Path,
    output_dir: str | Path,
    *,
    image_dirs: Sequence[str | Path] | None = None,
    files: ConversionFiles,
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
        files=files,
    )

    files.validate_yolo_output(ctx)
    files.prepare_yolo_output(ctx.output_dir, ctx.splits)

    box_df = ctx.df[ctx.df["instance_shape"] == "box"].copy()
    none_df = ctx.df[ctx.df["instance_shape"] == "none"].copy()

    images_processed: set[str] = set()
    adjustments = _write_box_labels(
        box_df,
        ctx.output_dir,
        ctx.label_map,
        ctx.found,
        ctx.link_mode,
        images_processed,
        files=files,
    )
    _write_none_labels(
        none_df,
        ctx.output_dir,
        ctx.found,
        ctx.link_mode,
        images_processed,
        files=files,
        box_images=set(box_df[["image_name", "split"]].itertuples(index=False, name=None)),
    )
    files.prune_yolo_output(ctx)
    _write_dataset_yaml(ctx.output_dir, ctx.splits, ctx.label_map, files)

    adjustments.warn()
    logger.info(
        f"Готово: {len(images_processed)} изображений, {len(box_df) - adjustments.dropped} боксов, "
        f"{len(ctx.label_map)} классов -> {ctx.output_dir}"
    )
    return ctx.output_dir


def _parse_label_file(path: Path, *, files: ConversionFiles) -> list[list[float]]:
    text = files.label_text(path)
    return [] if text is None else _parse_label_text(text, path)


def _labels_or_skip(path: Path, unreadable: list[Path], *, files: ConversionFiles) -> list[list[float]] | None:
    """Parse *path*, or warn, record it in *unreadable* and return ``None``."""
    try:
        return _parse_label_file(path, files=files)
    except UnreadableLabelError as exc:
        logger.warning(f"Пропуск: {exc}")
        unreadable.append(path)
        return None


def _warn_unreadable_labels(unreadable: list[Path]) -> None:
    if unreadable:
        logger.warning(
            f"Пропущено нечитаемых файлов разметки: {len(unreadable)} "
            f"({preview_names([str(path) for path in unreadable])})"
        )


def _from_yolo_dataset(
    yaml_path: Path,
    output_path: Path,
    *,
    read_all_sizes: bool,
    files: ConversionFiles,
) -> None:
    """Convert YOLO dataset (with dataset.yaml) to CSV."""
    ds_config = files.load_yaml(yaml_path)
    if not isinstance(ds_config, dict):
        raise Cveta2Error(f"Ошибка: {yaml_path} не содержит YAML-словарь")

    class_names = _normalize_class_names(ds_config.get("names", {}), yaml_path)
    if not class_names:
        raise Cveta2Error(f"Ошибка: в {yaml_path} не найдены имена классов (names)")

    sizes = _SizeCache(files=files, read_all=read_all_sizes)
    dataset_root = files.resolve_dataset_root(yaml_path, ds_config.get("path"))

    rows: list[dict[str, object]] = []
    frame_id = 0
    annotation_id = 1
    unreadable: list[Path] = []

    for split_key in ("train", "val", "test"):
        split_val = ds_config.get(split_key)
        if not split_val:
            continue

        for img_path in files.split_images(split_val, dataset_root):
            if not files.image_available(img_path):
                logger.warning(f"Изображение из списка не найдено: {img_path}")
                continue

            labels = _labels_or_skip(_label_path_for_image(img_path), unreadable, files=files)
            if labels is None:
                continue
            img_w, img_h = sizes.get(img_path)
            _require_positive_dimensions(img_w, img_h, img_path.name)

            if not labels:
                rows.append(
                    _make_csv_row_base(
                        "none",
                        img_path.name,
                        (img_w, img_h),
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

    _warn_unreadable_labels(unreadable)
    files.write_conversion_csv(rows, output_path)


def _from_yolo_predictions(  # noqa: PLR0913
    input_dir: Path,
    output_path: Path,
    names_file: Path | None,
    *,
    image_dirs: Sequence[str | Path] | None,
    read_all_sizes: bool,
    files: ConversionFiles,
) -> None:
    """Convert bare YOLO prediction .txt files to CSV."""
    class_names = files.load_class_names(names_file) if names_file else {}
    search_dirs = [Path(directory) for directory in image_dirs or ()]

    label_files = files.prediction_labels(input_dir)
    if not label_files:
        raise Cveta2Error(f"Ошибка: не найдено .txt файлов в {input_dir}")

    sizes = _SizeCache(files=files, read_all=read_all_sizes)

    rows: list[dict[str, object]] = []
    frame_id = 0
    annotation_id = 1
    missing_images: list[str] = []
    unreadable: list[Path] = []

    for label_path in label_files:
        labels = _labels_or_skip(label_path, unreadable, files=files)
        if not labels:
            continue

        img_path = files.find_image_by_stem(
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
        logger.warning(f"Не найдены изображения для {len(missing_images)} файлов: {preview_names(missing_images)}")
    _warn_unreadable_labels(unreadable)

    files.write_conversion_csv(rows, output_path)


def convert_from_yolo(  # noqa: PLR0913
    input_dir: str | Path,
    output_csv: str | Path,
    *,
    files: ConversionFiles,
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
    if files.dataset_yaml_available(yaml_path):
        logger.info(f"Режим датасета: найден {yaml_path}")
        _from_yolo_dataset(
            yaml_path,
            output_path,
            read_all_sizes=read_all_sizes,
            files=files,
        )
    else:
        logger.info("Режим предсказаний: dataset.yaml не найден")
        _from_yolo_predictions(
            in_dir,
            output_path,
            names_path,
            image_dirs=image_dirs,
            read_all_sizes=read_all_sizes,
            files=files,
        )
    return output_path

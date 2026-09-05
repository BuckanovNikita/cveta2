"""CSV <-> YOLO detection format conversion services."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict

import yaml
from loguru import logger

from cveta2.exceptions import Cveta2Error
from cveta2.services.convert.common import (
    _IMAGE_EXTENSIONS,
    ExportContext,
    PixelBox,
    YoloBox,
    _build_search_dirs,
    _find_image_by_stem,
    _link_or_copy,
    _make_csv_row_base,
    _make_csv_row_box,
    _pixel_to_yolo,
    _require_positive_dimensions,
    _SizeCache,
    _write_csv,
    _yolo_to_pixel,
    prepare_export,
)
from cveta2.services.output import preview_names, read_text_utf8, write_text_utf8

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pandas as pd


class _YamlDumpOptions(TypedDict):
    """Serializer knobs for ``dataset.yaml``; ``yaml.safe_load`` ignores both."""

    default_flow_style: bool
    allow_unicode: bool


_YAML_DUMP: _YamlDumpOptions = {"default_flow_style": False, "allow_unicode": False}

_YOLO_BOX_FIELDS = 5
"""``class xc yc w h`` — the shortest label line YOLO defines."""

_YOLO_CONF_FIELDS = _YOLO_BOX_FIELDS + 1
"""A prediction line appends a confidence score to the box fields."""


def _write_box_labels(  # noqa: PLR0913, PLR0917
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
        write_text_utf8(label_path, "\n".join(lines) + "\n")


def _write_none_labels(  # noqa: PLR0913
    none_df: pd.DataFrame,
    output_dir: Path,
    found: dict[str, Path],
    link_mode: str,
    images_processed: set[str],
    *,
    box_images: set[tuple[str, str]],
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
        if (image_name, split) not in box_images:
            write_text_utf8(label_path, "")


def _prune_yolo_output(ctx: ExportContext) -> None:
    """Remove files for images and splits absent from the current export."""
    expected_images: set[Path] = set()
    expected_labels: set[Path] = set()
    for name, split in ctx.df[["image_name", "split"]].itertuples(
        index=False, name=None
    ):
        expected_images.add(ctx.output_dir / "images" / split / name)
        expected_labels.add(
            ctx.output_dir / "labels" / split / f"{Path(name).stem}.txt"
        )
    for directory, expected, suffixes in (
        ("images", expected_images, _IMAGE_EXTENSIONS),
        ("labels", expected_labels, (".txt",)),
    ):
        tree = ctx.output_dir / directory
        if tree.is_symlink():
            continue
        for path in tree.glob("*/*"):
            if (
                path.suffix.lower() in suffixes
                and path not in expected
                and not path.parent.is_symlink()
                and (path.is_file() or path.is_symlink())
            ):
                path.unlink()


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

    write_text_utf8(output_dir / "dataset.yaml", yaml.dump(yaml_data, **_YAML_DUMP))


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
        box_images=set(
            box_df[["image_name", "split"]].itertuples(index=False, name=None)
        ),
    )
    _prune_yolo_output(ctx)
    _write_dataset_yaml(ctx.output_dir, ctx.splits, ctx.label_map)

    logger.info(
        f"Готово: {len(images_processed)} изображений, {len(box_df)} боксов, "
        f"{len(ctx.label_map)} классов -> {ctx.output_dir}"
    )
    return ctx.output_dir


def _parse_label_file(path: Path) -> list[list[float]]:
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
    if not path.is_file():
        return []
    rows: list[list[float]] = []
    skipped = 0
    extra_fields = 0
    for line in read_text_utf8(path).strip().splitlines():
        parts = line.strip().split()
        if len(parts) < _YOLO_BOX_FIELDS:
            skipped += 1
            continue
        try:
            rows.append([float(part) for part in parts])
        except ValueError:
            skipped += 1
            continue
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
        return {index: str(name) for index, name in enumerate(names)}
    if isinstance(names, dict):
        return {int(k): str(v) for k, v in names.items()}
    raise Cveta2Error(f"Ошибка: names в {source} должен быть списком или словарём")


def _load_class_names_yaml(path: Path) -> dict[int, str]:
    """Load class names from a YAML file (supports {names: ...} or flat dict)."""
    if not path.is_file():
        raise Cveta2Error(f"Ошибка: файл имён классов не найден: {path}")
    data = yaml.safe_load(read_text_utf8(path))
    if isinstance(data, dict) and "names" in data:
        return _normalize_class_names(data["names"], path)
    if isinstance(data, dict):
        return _normalize_class_names(data, path)
    return {}


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


def _resolve_dataset_root(yaml_path: Path, raw_root: object) -> Path:
    """Resolve YOLO's optional ``path`` relative to the dataset YAML."""
    if raw_root in (None, ""):
        return yaml_path.parent.resolve()
    root = Path(str(raw_root)).expanduser()
    if not root.is_absolute():
        root = yaml_path.parent / root
    return root.resolve()


def _resolve_listed_image(raw: str, list_path: Path, dataset_root: Path) -> Path:
    """Resolve one image named by a YOLO split list file."""
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    if raw.startswith("./"):
        return (list_path.parent / raw[2:]).absolute()
    return (dataset_root / path).absolute()


def _images_from_split_source(source: Path, dataset_root: Path) -> list[Path]:
    """Expand one YOLO split directory, image, or image-list file."""
    if source.is_dir():
        return sorted(
            path
            for path in source.rglob("*")
            if path.is_file() and path.suffix.lower() in _IMAGE_EXTENSIONS
        )
    if source.is_file() and source.suffix.lower() == ".txt":
        images: list[Path] = []
        for line in read_text_utf8(source).splitlines():
            raw = line.strip()
            if raw:
                images.append(_resolve_listed_image(raw, source, dataset_root))
        return images
    if source.is_file() and source.suffix.lower() in _IMAGE_EXTENSIONS:
        return [source]
    logger.warning(f"Источник изображений не найден: {source}")
    return []


def _split_images(raw_split: object, dataset_root: Path) -> list[Path]:
    """Resolve a YOLO split value while preserving declared source order."""
    entries = raw_split if isinstance(raw_split, list) else [raw_split]
    result: list[Path] = []
    seen: set[Path] = set()
    for entry in entries:
        if not isinstance(entry, (str, Path)):
            raise Cveta2Error(
                f"Ошибка: путь split должен быть строкой или списком строк, "
                f"получено {entry!r}"
            )
        source = Path(entry).expanduser()
        if not source.is_absolute():
            source = dataset_root / source
        for image in _images_from_split_source(source.absolute(), dataset_root):
            # Labels belong to the dataset path, even when its image is a symlink.
            resolved = image.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(image.absolute())
    return result


def _label_path_for_image(img_path: Path) -> Path:
    """Return the conventional YOLO label path for an image path."""
    parts = list(img_path.parts)
    image_indexes = [index for index, part in enumerate(parts) if part == "images"]
    if image_indexes:
        parts[image_indexes[-1]] = "labels"
        return Path(*parts).with_suffix(".txt")
    return img_path.with_suffix(".txt")


def _from_yolo_dataset(
    yaml_path: Path,
    output_path: Path,
    *,
    read_all_sizes: bool,
) -> None:
    """Convert YOLO dataset (with dataset.yaml) to CSV."""
    ds_config = yaml.safe_load(read_text_utf8(yaml_path))
    if not isinstance(ds_config, dict):
        raise Cveta2Error(f"Ошибка: {yaml_path} не содержит YAML-словарь")

    class_names = _normalize_class_names(ds_config.get("names", {}), yaml_path)
    if not class_names:
        raise Cveta2Error(f"Ошибка: в {yaml_path} не найдены имена классов (names)")

    sizes = _SizeCache(read_all=read_all_sizes)
    dataset_root = _resolve_dataset_root(yaml_path, ds_config.get("path"))

    rows: list[dict[str, object]] = []
    frame_id = 0
    annotation_id = 1

    for split_key in ("train", "val", "test"):
        split_val = ds_config.get(split_key)
        if not split_val:
            continue

        for img_path in _split_images(split_val, dataset_root):
            if not img_path.is_file():
                logger.warning(f"Изображение из списка не найдено: {img_path}")
                continue

            img_w, img_h = sizes.get(img_path)
            _require_positive_dimensions(img_w, img_h, img_path.name)
            labels = _parse_label_file(_label_path_for_image(img_path))

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
            f"{preview_names(missing_images)}"
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

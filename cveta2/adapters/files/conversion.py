"""Local conversion file access, image discovery, and owned-output lifecycle."""

import json
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

from cveta2.adapters.files.dataset import (
    LocalDatasetFiles,
    read_text_utf8,
    write_text_utf8,
)
from cveta2.adapters.files.image_search import resolve_images
from cveta2.adapters.files.materialization import _link_or_copy
from cveta2.domain.conversion import (
    _IMAGE_EXTENSIONS,
    ExportContext,
    _normalize_class_names,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import CSV_COLUMNS
from cveta2.domain.output import CSV_WRITE_OPTIONS, format_counts_ru


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


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    """Write rows to CSV with proper column order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=list(CSV_COLUMNS))
    df.to_csv(path, **CSV_WRITE_OPTIONS)
    logger.info(f"CSV сохранён: {path} ({format_counts_ru(df)})")


def _load_yaml(path: Path) -> object:
    """Translate expected external YAML failures at the file boundary."""
    try:
        return yaml.safe_load(read_text_utf8(path))
    except (yaml.YAMLError, UnicodeError, OSError) as exc:
        raise Cveta2Error(f"Ошибка: не удалось прочитать YAML {path}: {exc}") from exc


def _load_class_names_yaml(path: Path) -> dict[int, str]:
    """Load class names from a YAML file (supports {names: ...} or flat dict)."""
    if not path.is_file():
        raise Cveta2Error(f"Ошибка: файл имён классов не найден: {path}")
    data = _load_yaml(path)
    if isinstance(data, dict) and "names" in data:
        return _normalize_class_names(data["names"], path)
    if isinstance(data, dict):
        return _normalize_class_names(data, path)
    raise Cveta2Error(f"Ошибка: {path} не содержит имена классов")


def _resolve_dataset_root(yaml_path: Path, raw_root: object) -> Path:
    """Resolve YOLO's optional ``path`` relative to the dataset YAML."""
    if raw_root in (None, ""):
        return yaml_path.parent.resolve()
    if not isinstance(raw_root, (str, Path)):
        raise Cveta2Error(f"Ошибка: path в {yaml_path} должен быть строкой")
    root = Path(raw_root).expanduser()
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


def _prepare_yolo_output(output_dir: Path, splits: list[str]) -> None:
    """Read optional label text."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for split in splits:
        (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)


def _prepare_coco_split(directory: Path) -> None:
    """Read optional label text."""
    directory.mkdir(parents=True, exist_ok=True)


def _label_text(path: Path) -> str | None:
    """Read optional label text."""
    return read_text_utf8(path) if path.is_file() else None


class LocalConversionFiles(LocalDatasetFiles):
    """Concrete effects required by conversion workflows."""

    resolve_images = staticmethod(resolve_images)
    find_image_by_stem = staticmethod(_find_image_by_stem)
    image_size = staticmethod(_get_image_size)
    write_conversion_csv = staticmethod(_write_csv)
    load_yaml = staticmethod(_load_yaml)
    load_class_names = staticmethod(_load_class_names_yaml)
    resolve_dataset_root = staticmethod(_resolve_dataset_root)
    split_images = staticmethod(_split_images)
    prune_yolo_output = staticmethod(_prune_yolo_output)
    coco_owned_paths = staticmethod(_coco_owned_paths)
    prune_coco_output = staticmethod(_prune_coco_output)
    prepare_yolo_output = staticmethod(_prepare_yolo_output)
    prepare_coco_output = staticmethod(_prepare_coco_split)
    prepare_coco_split = staticmethod(_prepare_coco_split)
    label_text = staticmethod(_label_text)
    materialize_image = staticmethod(_link_or_copy)
    write_output_text = staticmethod(write_text_utf8)

    @staticmethod
    def dataset_yaml_available(path: Path) -> bool:
        """Check whether the dataset YAML exists."""
        return path.is_file()

    @staticmethod
    def image_available(path: Path) -> bool:
        """Check whether a declared image exists."""
        return path.is_file()

    @staticmethod
    def prediction_labels(path: Path) -> list[Path]:
        """List prediction label files in deterministic order."""
        return sorted(path.glob("**/*.txt"))

    @staticmethod
    def resolved_output_dir(path: Path) -> Path:
        """Resolve the dataset root written to YOLO metadata."""
        return path.resolve()

"""Production conversion/merge composition preserving workflow signatures."""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pandas as pd

from cveta2.adapters.config.settings import ImageCacheConfig
from cveta2.adapters.files.conversion import LocalConversionFiles
from cveta2.adapters.files.dataset import LocalDatasetFiles
from cveta2.application.use_cases.convert.coco import convert_to_coco as export_coco
from cveta2.application.use_cases.convert.yolo import convert_from_yolo as import_yolo
from cveta2.application.use_cases.convert.yolo import convert_to_yolo as export_yolo
from cveta2.application.use_cases.merge import merge_datasets as merge
from cveta2.application.use_cases.whats_new import compute_baseline as baseline
from cveta2.domain.baseline import WhatsNewBaseline


def _build_search_dirs(image_dir_args: Sequence[str | Path] | None) -> list[Path]:
    """Resolve command-provided directories and configured cache search values."""
    dirs = [Path(directory) for directory in image_dir_args or ()]
    for cache_dir in ImageCacheConfig.load().projects.values():
        if cache_dir not in dirs:
            dirs.append(cache_dir)
    return dirs


def convert_to_yolo(
    dataset: str | Path,
    output_dir: str | Path,
    *,
    image_dirs: Sequence[str | Path] | None = None,
    link_mode: Literal["auto", "reflink", "hardlink", "symlink", "copy"] = "auto",
) -> Path:
    """Compose production dependencies and export YOLO."""
    return export_yolo(
        dataset,
        output_dir,
        image_dirs=_build_search_dirs(image_dirs),
        link_mode=link_mode,
        files=LocalConversionFiles(),
    )


def convert_to_coco(
    dataset: str | Path,
    output_dir: str | Path,
    *,
    image_dirs: Sequence[str | Path] | None = None,
    link_mode: Literal["auto", "reflink", "hardlink", "symlink", "copy"] = "auto",
) -> Path:
    """Compose production dependencies and export COCO."""
    return export_coco(
        dataset,
        output_dir,
        image_dirs=_build_search_dirs(image_dirs),
        link_mode=link_mode,
        files=LocalConversionFiles(),
    )


def convert_from_yolo(
    input_dir: str | Path,
    output_csv: str | Path,
    *,
    names_file: str | Path | None = None,
    read_all_sizes: bool = False,
    image_dirs: Sequence[str | Path] | None = None,
) -> Path:
    """Compose production dependencies and import YOLO."""
    files = LocalConversionFiles()
    search_dirs = (
        list(image_dirs or ())
        if files.dataset_yaml_available(Path(input_dir) / "dataset.yaml")
        else _build_search_dirs(image_dirs)
    )
    return import_yolo(
        input_dir,
        output_csv,
        names_file=names_file,
        read_all_sizes=read_all_sizes,
        image_dirs=search_dirs,
        files=files,
    )


def merge_datasets(
    old: str | Path,
    new: str | Path,
    output: str | Path,
    *,
    deleted: str | Path | None = None,
    by_task: bool = False,
) -> pd.DataFrame:
    """Compose production dependencies and merge dataset CSVs."""
    return merge(
        old, new, output, deleted=deleted, by_task=by_task, files=LocalDatasetFiles()
    )


def compute_baseline(df: pd.DataFrame, path: Path) -> WhatsNewBaseline:
    """Compose persistence for a dataset baseline."""
    return baseline(df, path, files=LocalDatasetFiles())

"""Pure dataset serialization settings and human-readable summaries."""

from collections.abc import Hashable, Sequence
from typing import TypedDict

import pandas as pd

_UTF8 = "utf-8"
"""The one codec every file this project reads or writes is encoded in."""


class _CsvReadOptions(TypedDict):
    """Reader knobs shared by every CSV this project reads."""

    encoding: str
    dtype: dict[Hashable, type[str]]
    keep_default_na: bool
    na_values: list[str]


class _CsvWriteOptions(TypedDict):
    """Writer knobs shared by every CSV this project writes."""

    index: bool
    encoding: str


_CSV_TEXT_COLUMNS = (
    "image_name",
    "instance_shape",
    "instance_label",
    "task_name",
    "job_stage",
    "job_state",
    "task_updated_date",
    "created_by_username",
    "split",
    "subset",
    "source",
    "issue_text",
    "issue_state",
    "s3_image_path",
    "image_path",
    "attributes",
)
"""Textual schema fields must retain leading zeros and literal names like NA."""

CSV_READ_OPTIONS: _CsvReadOptions = {
    "encoding": _UTF8,
    "dtype": dict.fromkeys(_CSV_TEXT_COLUMNS, str),
    "keep_default_na": False,
    "na_values": [""],
}
CSV_WRITE_OPTIONS: _CsvWriteOptions = {"index": False, "encoding": _UTF8}


PREVIEW_LIMIT = 10
"""How many example names log messages show before collapsing the rest."""


def preview_names(names: Sequence[str], limit: int = PREVIEW_LIMIT) -> str:
    """Format ``"a, b, c (и ещё N)"``: the first *limit* names plus a rest count."""
    shown = ", ".join(str(name) for name in names[:limit])
    extra = len(names) - limit
    return f"{shown} (и ещё {extra})" if extra > 0 else shown


def count_images(df: pd.DataFrame) -> int:
    """Count unique images in an annotation DataFrame (0 when empty)."""
    if "image_name" not in df.columns:
        return 0
    return int(df["image_name"].nunique())


def format_counts(df: pd.DataFrame) -> str:
    """English ``N images, M rows`` summary for log messages."""
    return f"{count_images(df)} images, {len(df)} rows"


def format_counts_ru(df: pd.DataFrame) -> str:
    """Russian ``N изображений, M строк`` summary for log messages."""
    return f"{count_images(df)} изображений, {len(df)} строк"


CSV_LABELS: dict[str, str] = {
    "raw.csv": "Raw CSV",
    "dataset.csv": "Dataset CSV",
    "obsolete.csv": "Obsolete CSV",
    "in_progress.csv": "In-progress CSV",
    "deleted.csv": "Deleted CSV",
}
"""Human-readable name each output CSV is logged under."""

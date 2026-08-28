"""Tests for cveta2.services.output: CSV validation, previews and writers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from cveta2.dataset_partition import PartitionResult
from cveta2.exceptions import Cveta2Error
from cveta2.models import CSV_COLUMNS, ProjectAnnotations
from cveta2.services.output import (
    PREVIEW_LIMIT,
    preview_names,
    read_dataset_csv,
    write_dataset_and_deleted,
    write_partition_csvs,
    write_raw_csv,
)
from tests.helpers import csv_row, make_bbox, make_deleted, make_df, write_dataset_csv

if TYPE_CHECKING:
    from pathlib import Path


def _annotations() -> ProjectAnnotations:
    """One annotated image plus one deleted image."""
    return ProjectAnnotations(
        annotations=[make_bbox(image_name="kept.jpg")],
        deleted_images=[make_deleted("gone.jpg", task_id=7, updated="2026-02-02")],
    )


def _partition() -> PartitionResult:
    """Build a partition with one row in each of the three frames."""
    return PartitionResult(
        dataset=make_df([csv_row("kept.jpg")]),
        obsolete=make_df([csv_row("stale.jpg", task_id=2)]),
        in_progress=make_df([csv_row("wip.jpg", task_id=3, status="annotation")]),
        deleted_images=[make_deleted("gone.jpg", task_id=7, updated="2026-02-02")],
    )


# ---------------------------------------------------------------------------
# read_dataset_csv
# ---------------------------------------------------------------------------


def test_read_dataset_csv_returns_rows(tmp_path: Path) -> None:
    """A valid CSV is returned with all of its rows."""
    path = write_dataset_csv(tmp_path / "d.csv", [csv_row("a.jpg"), csv_row("b.jpg")])
    df = read_dataset_csv(path, {"image_name"})
    assert list(df["image_name"]) == ["a.jpg", "b.jpg"]


def test_read_dataset_csv_missing_file_names_the_path(tmp_path: Path) -> None:
    """The not-found error names the file the user asked for.

    The old tests only asserted that ``Cveta2Error`` was raised, so replacing
    the whole message with ``None`` left them green.
    """
    missing = tmp_path / "nope.csv"
    with pytest.raises(Cveta2Error, match=re.escape(str(missing))):
        read_dataset_csv(missing, {"image_name"})


def test_read_dataset_csv_lists_missing_columns_alphabetically(tmp_path: Path) -> None:
    """The error lists every missing column, sorted and comma-joined.

    Nothing pinned the message, so both dropping it entirely and changing the
    ``", "`` separator between column names survived.
    """
    path = write_dataset_csv(tmp_path / "d.csv", [{"image_name": "a.jpg"}])
    with pytest.raises(Cveta2Error, match="task_id, task_name"):
        read_dataset_csv(path, {"image_name", "task_name", "task_id"})


def test_read_dataset_csv_by_task_error_names_the_column(tmp_path: Path) -> None:
    """The --by-task error names the column that is missing.

    Without this the message could be replaced by ``None`` unnoticed.
    """
    path = write_dataset_csv(tmp_path / "d.csv", [{"image_name": "a.jpg"}])
    with pytest.raises(Cveta2Error, match="task_id"):
        read_dataset_csv(path, {"image_name"}, require_task_id_column=True)


# ---------------------------------------------------------------------------
# preview_names
# ---------------------------------------------------------------------------


def test_preview_names_joins_with_comma_space() -> None:
    """Names below the limit are joined by ``", "`` and get no suffix."""
    assert preview_names(["a", "b", "c"]) == "a, b, c"


def test_preview_names_at_limit_has_no_suffix() -> None:
    """Exactly PREVIEW_LIMIT names are all shown, with no "и ещё" tail.

    Callers only ever passed 2 or 15 names, which cannot tell ``extra > 0``
    from ``extra >= 0``: at the boundary the latter appends "(и ещё 0)".
    """
    names = [f"img{i}.jpg" for i in range(PREVIEW_LIMIT)]
    assert preview_names(names) == ", ".join(names)


def test_preview_names_one_over_limit_reports_one_extra() -> None:
    """A single hidden name is still reported, which ``extra > 1`` would drop."""
    names = [f"img{i}.jpg" for i in range(PREVIEW_LIMIT + 1)]
    result = preview_names(names)
    assert result.endswith("(и ещё 1)")
    assert names[PREVIEW_LIMIT] not in result


def test_preview_names_honours_explicit_limit() -> None:
    """An explicit *limit* overrides PREVIEW_LIMIT for both halves."""
    assert preview_names(["a", "b", "c", "d"], limit=2) == "a, b (и ещё 2)"


# ---------------------------------------------------------------------------
# write_raw_csv
# ---------------------------------------------------------------------------


def test_write_raw_csv_creates_nested_dir_and_is_repeatable(tmp_path: Path) -> None:
    """raw.csv lands in a directory whose parents do not exist yet.

    Nothing exercised a nested output path (``parents=True``) or a second run
    into an existing directory (``exist_ok=True``), so both mkdir flags could
    be flipped without any test noticing.
    """
    output_dir = tmp_path / "run" / "out"
    write_raw_csv(_annotations(), output_dir)
    write_raw_csv(_annotations(), output_dir)

    df = pd.read_csv(output_dir / "raw.csv")
    assert list(df.columns) == list(CSV_COLUMNS)
    assert set(df["image_name"]) == {"kept.jpg", "gone.jpg"}


# ---------------------------------------------------------------------------
# write_partition_csvs
# ---------------------------------------------------------------------------


def test_write_partition_csvs_creates_nested_dir_and_is_repeatable(
    tmp_path: Path,
) -> None:
    """All four CSVs land in a not-yet-existing nested directory, twice.

    Same gap as raw.csv: no caller wrote a partition into a nested path.
    """
    output_dir = tmp_path / "run" / "out"
    write_partition_csvs(_partition(), output_dir)
    write_partition_csvs(_partition(), output_dir)

    for name, image in [
        ("dataset.csv", "kept.jpg"),
        ("obsolete.csv", "stale.jpg"),
        ("in_progress.csv", "wip.jpg"),
        ("deleted.csv", "gone.jpg"),
    ]:
        df = pd.read_csv(output_dir / name)
        assert list(df.columns) == list(CSV_COLUMNS), name
        assert list(df["image_name"]) == [image], name


# ---------------------------------------------------------------------------
# write_dataset_and_deleted
# ---------------------------------------------------------------------------


def test_write_dataset_and_deleted_creates_nested_dir_and_is_repeatable(
    tmp_path: Path,
) -> None:
    """dataset.csv and deleted.csv land in a nested directory, twice."""
    output_dir = tmp_path / "run" / "out"
    write_dataset_and_deleted(_annotations(), output_dir)
    write_dataset_and_deleted(_annotations(), output_dir)

    dataset = pd.read_csv(output_dir / "dataset.csv")
    assert list(dataset["image_name"]) == ["kept.jpg"]
    deleted = pd.read_csv(output_dir / "deleted.csv")
    assert list(deleted["image_name"]) == ["gone.jpg"]
    assert deleted.loc[0, "task_id"] == 7


def test_deleted_csv_keeps_full_header_when_empty(tmp_path: Path) -> None:
    """An empty deleted.csv still carries every CSV column, in order.

    Only the empty case can tell the explicit ``columns=CSV_COLUMNS`` apart
    from letting pandas infer the columns from the rows.
    """
    result = ProjectAnnotations(annotations=[make_bbox()], deleted_images=[])
    write_dataset_and_deleted(result, tmp_path)

    header = (tmp_path / "deleted.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == list(CSV_COLUMNS)

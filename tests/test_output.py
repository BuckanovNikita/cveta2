"""Tests for cveta2.adapters.files.dataset: CSV validation, previews and writers."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cveta2.adapters.files.dataset import (
    read_dataset_csv,
    write_dataset_and_deleted,
    write_partition_csvs,
    write_raw_csv,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import CSV_COLUMNS, ProjectAnnotations
from cveta2.domain.output import PREVIEW_LIMIT, preview_names
from cveta2.domain.partition import PartitionResult, partition_annotations_df
from tests.helpers import csv_row, make_bbox, make_deleted, make_df, write_dataset_csv


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


_TEXT_COLUMNS = ("instance_label", "image_name", "task_name", "issue_text")
# Cell text as users write it: numeric-looking ids, NA spellings, separators,
# quotes and non-ASCII. An empty cell is the only spelling of a missing value.
_CELL_TEXT = st.one_of(
    st.sampled_from(["001", "NA", "null", "None", "nan", "1e3", " padded "]),
    st.text(st.characters(codec="utf-8", exclude_characters="\x00\r"), min_size=1),
)


@given(
    rows=st.lists(
        st.tuples(
            st.lists(st.one_of(st.just(""), _CELL_TEXT), min_size=4, max_size=4),
            st.integers(1, 10_000),
            st.one_of(st.none(), st.floats(0, 1)),
        ),
        min_size=1,
        max_size=4,
    )
)
def test_csv_round_trip_preserves_text_and_empty_cells(
    rows: list[tuple[list[str], int, float | None]],
) -> None:
    """Text columns read back verbatim; only an empty cell becomes missing.

    Numbers keep their numeric type next to the text columns.
    """
    records: list[dict[str, object]] = [
        dict(zip(_TEXT_COLUMNS, texts, strict=True))
        | {"image_width": width, "confidence": confidence}
        for texts, width, confidence in rows
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = write_dataset_csv(Path(tmp) / "strings.csv", records)
        df = read_dataset_csv(path, set(_TEXT_COLUMNS))

    for index, (texts, width, confidence) in enumerate(rows):
        for column, text in zip(_TEXT_COLUMNS, texts, strict=True):
            if text == "":
                assert pd.isna(df.loc[index, column]), column
            else:
                assert df.loc[index, column] == text, column
        assert df.loc[index, "image_width"] == width
        if confidence is None:
            assert pd.isna(df.loc[index, "confidence"])
        else:
            assert df.loc[index, "confidence"] == pytest.approx(confidence)


def test_read_dataset_csv_missing_file_names_the_path(tmp_path: Path) -> None:
    """The not-found error names the file the user asked for.

    The old tests only asserted that ``Cveta2Error`` was raised, so replacing
    the whole message with ``None`` left them green.
    """
    missing = tmp_path / "nope.csv"
    with pytest.raises(Cveta2Error, match=re.escape(str(missing))):
        read_dataset_csv(missing, {"image_name"})


def test_read_dataset_csv_blank_file_names_the_path(tmp_path: Path) -> None:
    """A file without even a header fails as ``Cveta2Error`` naming the file.

    pandas raises its own ``EmptyDataError`` here, which the CLI would print
    as a traceback instead of the clean exit every other bad input gets.
    """
    blank = tmp_path / "blank.csv"
    blank.write_bytes(b"\n")
    with pytest.raises(Cveta2Error, match=re.escape(str(blank))):
        read_dataset_csv(blank, {"image_name"})


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


@given(
    count=st.integers(0, PREVIEW_LIMIT + 3),
    limit=st.one_of(st.none(), st.integers(1, PREVIEW_LIMIT + 3)),
)
def test_preview_names_shows_the_first_names_and_counts_the_rest(
    count: int, limit: int | None
) -> None:
    """Shown names are joined by ``", "``; a hidden rest of N adds ``(и ещё N)``."""
    names = [f"img{i}.jpg" for i in range(count)]
    effective = PREVIEW_LIMIT if limit is None else limit
    result = preview_names(names) if limit is None else preview_names(names, limit)

    shown = ", ".join(names[:effective])
    hidden = count - effective
    assert result == (f"{shown} (и ещё {hidden})" if hidden > 0 else shown)


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


def test_raw_csv_keeps_full_header_when_empty(tmp_path: Path) -> None:
    """An empty raw.csv still carries every CSV column, in order."""
    write_raw_csv(ProjectAnnotations(annotations=[], deleted_images=[]), tmp_path)

    header = (tmp_path / "raw.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == list(CSV_COLUMNS)


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


def test_write_partition_csvs_of_empty_fetch_are_readable(tmp_path: Path) -> None:
    """Partitioning an empty fetch writes files ``read_dataset_csv`` accepts.

    Without the schema on the empty frame every partition CSV was a lone
    newline, which pandas refuses to parse.
    """
    empty = pd.DataFrame([], columns=list(CSV_COLUMNS))
    write_partition_csvs(partition_annotations_df(empty, []), tmp_path)

    for name in ("dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv"):
        df = read_dataset_csv(tmp_path / name, set(CSV_COLUMNS))
        assert list(df.columns) == list(CSV_COLUMNS), name
        assert len(df) == 0, name


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


def test_dataset_and_deleted_csv_keep_full_header_when_empty(tmp_path: Path) -> None:
    """Empty dataset.csv and deleted.csv still carry every CSV column, in order.

    ``fetch-task --completed-only`` on an unfinished task selects nothing;
    the files it leaves behind must still be ones ``upload`` can read. Only
    the empty case can tell explicit ``columns=CSV_COLUMNS`` apart from
    letting pandas infer the columns from the rows.
    """
    write_dataset_and_deleted(
        ProjectAnnotations(annotations=[], deleted_images=[]), tmp_path
    )

    for name in ("dataset.csv", "deleted.csv"):
        header = (tmp_path / name).read_text(encoding="utf-8").splitlines()[0]
        assert header.split(",") == list(CSV_COLUMNS), name
        assert len(read_dataset_csv(tmp_path / name, set(CSV_COLUMNS))) == 0, name

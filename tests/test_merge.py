"""Unit tests for merge: split propagation, by-time resolution, and I/O."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from cveta2.exceptions import Cveta2Error
from cveta2.services.merge import (
    _merge_datasets,
    _propagate_splits,
    _read_deleted_names,
    _resolve_by_time,
    merge_datasets,
)
from tests.helpers import csv_row, make_args, make_df, write_dataset_csv

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED = [
    "image_name",
    "instance_shape",
    "instance_label",
    "bbox_x_tl",
    "bbox_y_tl",
    "bbox_x_br",
    "bbox_y_br",
]


def _row(
    image: str,
    label: str = "cat",
    split: str | None = None,
    task_updated_date: str | None = None,
) -> dict[str, object]:
    if task_updated_date is None:
        return csv_row(image, label=label, split=split)
    return csv_row(image, label=label, split=split, updated=task_updated_date)


def _df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return make_df(rows)


# ---------------------------------------------------------------------------
# Split propagation — _propagate_splits directly
# ---------------------------------------------------------------------------


class TestPropagateSplits:
    """Tests for the _propagate_splits helper."""

    def test_split_propagated_to_new_rows(self) -> None:
        """Split from old is filled into merged rows where split is null."""
        old = _df([_row("a.jpg", split="train"), _row("b.jpg", split="val")])
        new = _df([_row("a.jpg"), _row("b.jpg")])
        merged = new.copy()
        common = {"a.jpg", "b.jpg"}

        result = _propagate_splits(merged, old, new, common)

        splits = result.set_index("image_name")["split"].to_dict()
        assert splits["a.jpg"] == "train"
        assert splits["b.jpg"] == "val"

    def test_no_propagation_when_old_has_no_split_column(
        self, capture_logs: list[str]
    ) -> None:
        """Warning emitted and no changes when old lacks split column."""
        old = pd.DataFrame(
            [
                {
                    "image_name": "a.jpg",
                    "instance_shape": "box",
                    "instance_label": "cat",
                    "bbox_x_tl": 0,
                    "bbox_y_tl": 0,
                    "bbox_x_br": 1,
                    "bbox_y_br": 1,
                },
            ]
        )
        new = _df([_row("a.jpg")])
        merged = new.copy()

        result = _propagate_splits(merged, old, new, {"a.jpg"})

        assert pd.isna(result["split"].iloc[0])
        assert any("нет данных split" in m for m in capture_logs)

    def test_no_propagation_when_old_splits_all_null(
        self, capture_logs: list[str]
    ) -> None:
        """Warning emitted when old has split column but all values are NaN."""
        old = _df([_row("a.jpg", split=None)])
        new = _df([_row("a.jpg")])
        merged = new.copy()

        _propagate_splits(merged, old, new, {"a.jpg"})

        assert any("нет данных split" in m for m in capture_logs)

    def test_conflict_warning_when_both_have_split(
        self, capture_logs: list[str]
    ) -> None:
        """Warning emitted when both old and new have non-null split for same image."""
        old = _df([_row("a.jpg", split="train")])
        new = _df([_row("a.jpg", split="test")])
        merged = new.copy()

        _propagate_splits(merged, old, new, {"a.jpg"})

        assert any("split задан в обоих датасетах" in m for m in capture_logs)

    def test_no_conflict_warning_when_only_old_has_split(
        self, capture_logs: list[str]
    ) -> None:
        """No conflict is reported when new has no split of its own.

        The user is told about disagreeing split data only when both sides
        actually carry a value.  Nothing pinned the negative case before, so
        widening either set operation behind the warning went unnoticed.
        """
        old = _df([_row("a.jpg", split="train")])
        new = _df([_row("a.jpg")])
        merged = new.copy()

        _propagate_splits(merged, old, new, {"a.jpg"})

        assert not any("split задан в обоих датасетах" in m for m in capture_logs)

    def test_first_old_row_wins_for_duplicate_image(self) -> None:
        """When old has two split values for one image, the first one is used.

        Both rows are non-null and differ only in ``split``, so deduplicating
        on all columns instead of on ``image_name`` keeps both and the later
        value silently overwrites the earlier one.
        """
        old = _df([_row("a.jpg", split="train"), _row("a.jpg", split="val")])
        new = _df([_row("a.jpg")])
        merged = new.copy()

        result = _propagate_splits(merged, old, new, {"a.jpg"})

        assert result["split"].iloc[0] == "train"

    def test_conflict_keeps_winner_split(self) -> None:
        """Winner's split value is preserved, not overwritten."""
        old = _df([_row("a.jpg", split="train")])
        new = _df([_row("a.jpg", split="test")])
        merged = new.copy()

        result = _propagate_splits(merged, old, new, {"a.jpg"})

        assert result["split"].iloc[0] == "test"

    def test_partial_propagation(self) -> None:
        """Rows with null split get propagated; existing split kept."""
        old = _df([_row("a.jpg", split="train"), _row("b.jpg", split="val")])
        new = _df([_row("a.jpg", split="test"), _row("b.jpg")])
        merged = new.copy()

        result = _propagate_splits(merged, old, new, {"a.jpg", "b.jpg"})

        splits = result.set_index("image_name")["split"].to_dict()
        assert splits["a.jpg"] == "test"
        assert splits["b.jpg"] == "val"


# ---------------------------------------------------------------------------
# Integration — _merge_datasets
# ---------------------------------------------------------------------------


class TestMergeDatasetsSplitPropagation:
    """Integration tests: split propagation through _merge_datasets."""

    def test_new_wins_propagates_old_split(self) -> None:
        """Default mode: new wins for common images, split from old is carried over."""
        old = _df([_row("a.jpg", split="train"), _row("b.jpg", split="val")])
        new = _df([_row("a.jpg"), _row("b.jpg"), _row("c.jpg")])

        merged = _merge_datasets(old, new, set())

        splits = merged.set_index("image_name")["split"].to_dict()
        assert splits["a.jpg"] == "train"
        assert splits["b.jpg"] == "val"
        assert pd.isna(splits["c.jpg"])

    def test_old_only_images_keep_split(self) -> None:
        """Images only in old retain their split values in merged output."""
        old = _df([_row("a.jpg", split="train")])
        new = _df([_row("b.jpg")])

        merged = _merge_datasets(old, new, set())

        a_split = merged.loc[merged["image_name"] == "a.jpg", "split"].iloc[0]
        assert a_split == "train"

    def test_deleted_images_excluded(self) -> None:
        """Deleted images are excluded, even if they had split in old."""
        old = _df([_row("a.jpg", split="train"), _row("b.jpg", split="val")])
        new = _df([_row("a.jpg"), _row("b.jpg")])

        merged = _merge_datasets(old, new, {"a.jpg"})

        assert "a.jpg" not in merged["image_name"].to_numpy()
        b_split = merged.loc[merged["image_name"] == "b.jpg", "split"].iloc[0]
        assert b_split == "val"

    def test_no_split_in_old_warns(self, capture_logs: list[str]) -> None:
        """Warning is logged when old dataset has no split data."""
        old = _df([_row("a.jpg")])
        new = _df([_row("a.jpg")])

        _merge_datasets(old, new, set())

        assert any("нет данных split" in m for m in capture_logs)

    def test_multiple_rows_per_image_propagated(self) -> None:
        """When an image has multiple annotation rows, all get the split from old."""
        old = _df([_row("a.jpg", label="cat", split="train")])
        new_rows = [_row("a.jpg", label="cat"), _row("a.jpg", label="dog")]
        new = _df(new_rows)

        merged = _merge_datasets(old, new, set())

        a_rows = merged[merged["image_name"] == "a.jpg"]
        assert len(a_rows) == 2
        assert (a_rows["split"] == "train").all()


class TestMergeDatasetsEdgeCases:
    """Edge cases for _merge_datasets."""

    def test_empty_old_preserves_new(self) -> None:
        """Empty old DataFrame -- all new images preserved."""
        old = _df([])
        new = _df([_row("a.jpg"), _row("b.jpg")])

        merged = _merge_datasets(old, new, set())

        assert set(merged["image_name"]) == {"a.jpg", "b.jpg"}

    def test_empty_new_preserves_old(self) -> None:
        """Empty new DataFrame -- all old images preserved."""
        old = _df([_row("a.jpg", split="train"), _row("b.jpg", split="val")])
        new = _df([])

        merged = _merge_datasets(old, new, set())

        assert set(merged["image_name"]) == {"a.jpg", "b.jpg"}

    def test_both_empty_no_crash(self) -> None:
        """Both DataFrames empty -- no crash, empty result."""
        old = _df([])
        new = _df([])

        merged = _merge_datasets(old, new, set())

        assert len(merged) == 0

    def test_merged_row_labels_are_unique(self) -> None:
        """Both sides contribute rows, so the result gets fresh row labels.

        Every other test reads the merged frame by column or by position, so
        nothing noticed that concatenating without re-indexing leaves the two
        sources' 0..n labels colliding — ``merged.loc[0]`` would then hand the
        caller two rows instead of one.
        """
        old = _df([_row("a.jpg"), _row("b.jpg")])
        new = _df([_row("c.jpg"), _row("d.jpg")])

        merged = _merge_datasets(old, new, set())

        assert merged.index.is_unique

    def test_disjoint_datasets_fully_preserved(self) -> None:
        """No common images -- both sides fully preserved."""
        old = _df([_row("a.jpg", split="train"), _row("b.jpg", split="val")])
        new = _df([_row("c.jpg"), _row("d.jpg")])

        merged = _merge_datasets(old, new, set())

        assert set(merged["image_name"]) == {"a.jpg", "b.jpg", "c.jpg", "d.jpg"}
        a_split = merged.loc[merged["image_name"] == "a.jpg", "split"].iloc[0]
        assert a_split == "train"


# ---------------------------------------------------------------------------
# By-time resolution — _resolve_by_time
# ---------------------------------------------------------------------------

_T_OLD = "2026-01-01T00:00:00+00:00"
_T_NEW = "2026-02-01T00:00:00+00:00"


def _trow(
    image: str,
    date: str | None = None,
    label: str = "cat",
    split: str | None = None,
) -> dict[str, object]:
    """Row helper that always includes task_updated_date."""
    d = _row(image, label=label, split=split)
    d["task_updated_date"] = date
    return d


def _tdf(rows: list[dict[str, object]]) -> pd.DataFrame:
    return make_df(rows)


class TestResolveByTime:
    """Unit tests for _resolve_by_time."""

    def test_new_newer_wins(self) -> None:
        old = _tdf([_trow("a.jpg", date=_T_OLD)])
        new = _tdf([_trow("a.jpg", date=_T_NEW)])

        result = _resolve_by_time(old, new, {"a.jpg"})

        assert result == {"a.jpg"}

    def test_old_newer_keeps_old(self) -> None:
        old = _tdf([_trow("a.jpg", date=_T_NEW)])
        new = _tdf([_trow("a.jpg", date=_T_OLD)])

        result = _resolve_by_time(old, new, {"a.jpg"})

        assert result == set()

    def test_equal_dates_new_wins(self) -> None:
        old = _tdf([_trow("a.jpg", date=_T_OLD)])
        new = _tdf([_trow("a.jpg", date=_T_OLD)])

        result = _resolve_by_time(old, new, {"a.jpg"})

        assert result == {"a.jpg"}

    def test_unparseable_old_date_falls_back_to_new(self) -> None:
        old = _tdf([_trow("a.jpg", date="not-a-date")])
        new = _tdf([_trow("a.jpg", date=_T_NEW)])

        result = _resolve_by_time(old, new, {"a.jpg"})

        assert result == {"a.jpg"}

    def test_unparseable_new_date_falls_back_to_new(self) -> None:
        old = _tdf([_trow("a.jpg", date=_T_OLD)])
        new = _tdf([_trow("a.jpg", date="not-a-date")])

        result = _resolve_by_time(old, new, {"a.jpg"})

        assert result == {"a.jpg"}

    def test_both_dates_unparseable_falls_back_to_new(self) -> None:
        old = _tdf([_trow("a.jpg", date="garbage")])
        new = _tdf([_trow("a.jpg", date="garbage")])

        result = _resolve_by_time(old, new, {"a.jpg"})

        assert result == {"a.jpg"}

    def test_multiple_rows_per_image_uses_max_date(self) -> None:
        """With multiple rows per image, the max date per side is compared."""
        old = _tdf(
            [
                _trow("a.jpg", date="2026-01-01T00:00:00+00:00", label="cat"),
                _trow("a.jpg", date="2026-01-15T00:00:00+00:00", label="dog"),
            ]
        )
        new = _tdf(
            [
                _trow("a.jpg", date="2026-01-10T00:00:00+00:00", label="cat"),
                _trow("a.jpg", date="2026-01-12T00:00:00+00:00", label="dog"),
            ]
        )

        result = _resolve_by_time(old, new, {"a.jpg"})

        # old max = Jan 15, new max = Jan 12 → old wins
        assert result == set()

    def test_dates_are_compared_as_instants(self) -> None:
        """A naive date on one side is read as UTC, not compared as wall time.

        Every other case here uses the same ``+00:00`` offset on both sides,
        so parsing without ``utc=True`` happened to agree.  Here old is naive
        and new carries an offset: without normalisation the two timestamps
        cannot be compared at all.
        """
        old = _tdf([_trow("a.jpg", date="2026-01-01T12:00:00")])
        new = _tdf([_trow("a.jpg", date="2026-01-01T10:00:00+03:00")])

        result = _resolve_by_time(old, new, {"a.jpg"})

        # new is 07:00 UTC, old is 12:00 UTC → old wins.
        assert result == set()

    def test_mixed_images_resolved_independently(self) -> None:
        old = _tdf(
            [
                _trow("a.jpg", date=_T_NEW),
                _trow("b.jpg", date=_T_OLD),
            ]
        )
        new = _tdf(
            [
                _trow("a.jpg", date=_T_OLD),
                _trow("b.jpg", date=_T_NEW),
            ]
        )

        result = _resolve_by_time(old, new, {"a.jpg", "b.jpg"})

        assert "a.jpg" not in result  # old is newer
        assert "b.jpg" in result  # new is newer


# ---------------------------------------------------------------------------
# Integration — _merge_datasets with by_time=True
# ---------------------------------------------------------------------------


class TestMergeDatasetsByTime:
    """Integration tests: by-time merge resolution through _merge_datasets."""

    def test_by_time_new_newer_keeps_new(self) -> None:
        old = _tdf([_trow("a.jpg", date=_T_OLD, label="cat")])
        new = _tdf([_trow("a.jpg", date=_T_NEW, label="dog")])

        merged = _merge_datasets(old, new, set(), by_time=True)

        assert len(merged) == 1
        assert merged.iloc[0]["instance_label"] == "dog"

    def test_by_time_old_newer_keeps_old(self) -> None:
        old = _tdf([_trow("a.jpg", date=_T_NEW, label="cat")])
        new = _tdf([_trow("a.jpg", date=_T_OLD, label="dog")])

        merged = _merge_datasets(old, new, set(), by_time=True)

        assert len(merged) == 1
        assert merged.iloc[0]["instance_label"] == "cat"

    def test_default_mode_ignores_dates(self) -> None:
        """Without --by-time new wins even when old carries a later date.

        The other default-mode tests leave every row on the same date, where
        date-based resolution would pick new anyway; only a strictly newer old
        row separates "new always wins" from "the later date wins".
        """
        old = _tdf([_trow("a.jpg", date=_T_NEW, label="old_a")])
        new = _tdf([_trow("a.jpg", date=_T_OLD, label="new_a")])

        merged = _merge_datasets(old, new, set())

        assert len(merged) == 1
        assert merged.iloc[0]["instance_label"] == "new_a"

    def test_by_time_deleted_still_excluded(self) -> None:
        old = _tdf(
            [
                _trow("a.jpg", date=_T_OLD, split="train"),
                _trow("b.jpg", date=_T_OLD, split="val"),
            ]
        )
        new = _tdf(
            [
                _trow("a.jpg", date=_T_NEW),
                _trow("b.jpg", date=_T_NEW),
            ]
        )

        merged = _merge_datasets(old, new, {"a.jpg"}, by_time=True)

        assert "a.jpg" not in merged["image_name"].to_numpy()
        assert "b.jpg" in merged["image_name"].to_numpy()

    def test_by_time_split_propagation(self) -> None:
        """Split from old propagated even when new wins via by_time."""
        old = _tdf([_trow("a.jpg", date=_T_OLD, split="train")])
        new = _tdf([_trow("a.jpg", date=_T_NEW)])

        merged = _merge_datasets(old, new, set(), by_time=True)

        assert merged.iloc[0]["split"] == "train"

    def test_by_time_only_old_and_only_new_preserved(self) -> None:
        """Images exclusive to one side are always kept."""
        old = _tdf([_trow("old_only.jpg", date=_T_OLD)])
        new = _tdf([_trow("new_only.jpg", date=_T_NEW)])

        merged = _merge_datasets(old, new, set(), by_time=True)

        names = set(merged["image_name"])
        assert names == {"old_only.jpg", "new_only.jpg"}

    def test_by_time_mixed_conflict_resolution(self) -> None:
        """Some common images won by old, some by new."""
        old = _tdf(
            [
                _trow("a.jpg", date=_T_NEW, label="old_a"),
                _trow("b.jpg", date=_T_OLD, label="old_b"),
            ]
        )
        new = _tdf(
            [
                _trow("a.jpg", date=_T_OLD, label="new_a"),
                _trow("b.jpg", date=_T_NEW, label="new_b"),
            ]
        )

        merged = _merge_datasets(old, new, set(), by_time=True)

        labels = merged.set_index("image_name")["instance_label"].to_dict()
        assert labels["a.jpg"] == "old_a"  # old was newer
        assert labels["b.jpg"] == "new_b"  # new was newer


# ---------------------------------------------------------------------------
# I/O helpers — _read_deleted_names
# ---------------------------------------------------------------------------


class TestReadDeletedNames:
    """Tests for _read_deleted_names."""

    def test_none_returns_empty_set(self) -> None:
        assert _read_deleted_names(None) == set()

    def test_csv_format_with_image_name_column(self, tmp_path: Path) -> None:
        """A multi-column CSV is parsed as CSV, not as one name per line.

        With a single-column file the legacy line-per-name reader returns the
        same names apart from the header, so it could stand in for the CSV
        reader unnoticed; the extra column makes the two disagree.
        """
        csv_path = tmp_path / "deleted.csv"
        csv_path.write_text(
            "image_name,reason\na.jpg,dup\nb.jpg,blurred\na.jpg,dup\n",
            encoding="utf-8",
        )

        result = _read_deleted_names(csv_path)

        assert result == {"a.jpg", "b.jpg"}

    def test_legacy_plain_text_format(self, tmp_path: Path) -> None:
        txt_path = tmp_path / "deleted.txt"
        txt_path.write_text("a.jpg\nb.jpg\n  \nc.jpg\n", encoding="utf-8")

        result = _read_deleted_names(txt_path)

        assert result == {"a.jpg", "b.jpg", "c.jpg"}

    def test_empty_file_yields_no_names(self, tmp_path: Path) -> None:
        """A file with only blank lines means "nothing deleted", not an error."""
        txt_path = tmp_path / "deleted.txt"
        txt_path.write_text("\n  \n", encoding="utf-8")

        assert _read_deleted_names(txt_path) == set()

    def test_missing_file_error_names_the_file(self, tmp_path: Path) -> None:
        """The error says which file is missing, not just that one is.

        The message was never asserted, so dropping its content left the user
        with a bare exception and no path to check.
        """
        missing = tmp_path / "does_not_exist.csv"

        with pytest.raises(Cveta2Error, match=re.escape(str(missing))):
            _read_deleted_names(missing)

    def test_malformed_csv_error_names_the_file(self, tmp_path: Path) -> None:
        """A parse failure is reported against the offending file."""
        csv_path = tmp_path / "deleted.csv"
        csv_path.write_text('image_name\n"unterminated,quote\n', encoding="utf-8")

        with pytest.raises(Cveta2Error, match=re.escape(str(csv_path))):
            _read_deleted_names(csv_path)


# ---------------------------------------------------------------------------
# I/O helpers — _read_dataset_csv (merge wrapper)
# ---------------------------------------------------------------------------


class TestReadDatasetCsvMerge:
    """Tests for _read_dataset_csv validation in merge context."""

    def test_by_time_without_time_column_exits(self, tmp_path: Path) -> None:
        from cveta2.services.merge import _read_dataset_csv

        csv_path = tmp_path / "dataset.csv"
        cols = [*_REQUIRED, "split"]
        csv_path.write_text(",".join(cols) + "\n", encoding="utf-8")

        with pytest.raises(Cveta2Error):
            _read_dataset_csv(csv_path, by_time=True)

    def test_missing_required_columns_exits(self, tmp_path: Path) -> None:
        from cveta2.services.merge import _read_dataset_csv

        csv_path = tmp_path / "dataset.csv"
        csv_path.write_text("image_name,split\na.jpg,train\n", encoding="utf-8")

        with pytest.raises(Cveta2Error):
            _read_dataset_csv(csv_path, by_time=False)

    def test_valid_csv_without_time_column_ok(self, tmp_path: Path) -> None:
        from cveta2.services.merge import _read_dataset_csv

        csv_path = tmp_path / "dataset.csv"
        row = _row("a.jpg")
        del row["task_updated_date"]
        df = pd.DataFrame([row])
        df.to_csv(csv_path, index=False, encoding="utf-8")

        result = _read_dataset_csv(csv_path, by_time=False)

        assert len(result) == 1


# ---------------------------------------------------------------------------
# Public entry point — merge_datasets (path-based I/O)
# ---------------------------------------------------------------------------


class TestMergeDatasetsIO:
    """Tests for merge_datasets with real temp files."""

    def test_basic_merge_output(self, tmp_path: Path) -> None:
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"

        write_dataset_csv(old_path, [_row("a.jpg", split="train")])
        write_dataset_csv(new_path, [_row("a.jpg"), _row("b.jpg")])

        merge_datasets(old_path, new_path, out_path)

        result = pd.read_csv(out_path)
        names = set(result["image_name"])
        assert names == {"a.jpg", "b.jpg"}
        a_split = result.loc[result["image_name"] == "a.jpg", "split"].iloc[0]
        assert a_split == "train"

    def test_merge_with_deleted(self, tmp_path: Path) -> None:
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        del_path = tmp_path / "deleted.csv"
        out_path = tmp_path / "merged.csv"

        write_dataset_csv(old_path, [_row("a.jpg"), _row("b.jpg")])
        write_dataset_csv(new_path, [_row("a.jpg"), _row("c.jpg")])
        del_path.write_text("image_name\na.jpg\n", encoding="utf-8")

        merge_datasets(old_path, new_path, out_path, deleted=del_path)

        result = pd.read_csv(out_path)
        names = set(result["image_name"])
        assert "a.jpg" not in names
        assert names == {"b.jpg", "c.jpg"}

    def test_merge_by_time(self, tmp_path: Path) -> None:
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"

        write_dataset_csv(
            old_path,
            [_trow("a.jpg", date=_T_NEW, label="old_label")],
        )
        write_dataset_csv(
            new_path,
            [_trow("a.jpg", date=_T_OLD, label="new_label")],
        )

        merge_datasets(old_path, new_path, out_path, by_time=True)

        result = pd.read_csv(out_path)
        assert result.iloc[0]["instance_label"] == "old_label"

    def test_by_time_missing_column_raises(self, tmp_path: Path) -> None:
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"

        no_time = _row("a.jpg")
        del no_time["task_updated_date"]
        write_dataset_csv(old_path, [dict(no_time)])
        write_dataset_csv(new_path, [dict(no_time)])

        with pytest.raises(Cveta2Error):
            merge_datasets(old_path, new_path, out_path, by_time=True)

    def test_by_time_missing_column_in_old_only_raises(self, tmp_path: Path) -> None:
        """--by-time validates the old CSV too, before any date is compared.

        With the column missing on one side only, skipping that side's check
        defers the failure to a raw pandas KeyError deep inside the merge
        instead of the guided Cveta2Error.
        """
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"

        no_time = _row("a.jpg")
        del no_time["task_updated_date"]
        write_dataset_csv(old_path, [dict(no_time)])
        write_dataset_csv(new_path, [_trow("a.jpg", date=_T_NEW)])

        with pytest.raises(Cveta2Error, match=re.escape(str(old_path))):
            merge_datasets(old_path, new_path, out_path, by_time=True)

    def test_by_time_missing_column_in_new_only_raises(self, tmp_path: Path) -> None:
        """--by-time validates the new CSV too, before any date is compared."""
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"

        no_time = _row("a.jpg")
        del no_time["task_updated_date"]
        write_dataset_csv(old_path, [_trow("a.jpg", date=_T_NEW)])
        write_dataset_csv(new_path, [dict(no_time)])

        with pytest.raises(Cveta2Error, match=re.escape(str(new_path))):
            merge_datasets(old_path, new_path, out_path, by_time=True)

    def test_default_mode_keeps_new_when_old_is_newer(self, tmp_path: Path) -> None:
        """Through the public entry point, --by-time off means new always wins.

        ``test_merge_by_time`` pins the opposite outcome for the same data, so
        without this pair the default of the ``by_time`` flag is unpinned.
        """
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"

        write_dataset_csv(old_path, [_trow("a.jpg", date=_T_NEW, label="old_label")])
        write_dataset_csv(new_path, [_trow("a.jpg", date=_T_OLD, label="new_label")])

        merge_datasets(old_path, new_path, out_path)

        result = pd.read_csv(out_path)
        assert result.iloc[0]["instance_label"] == "new_label"

    def test_output_parent_directories_are_created(self, tmp_path: Path) -> None:
        """A nested output path is created, parents included.

        Every other I/O test writes straight into tmp_path, which already
        exists, so nothing required the parents of the output file.
        """
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "runs" / "2026-01" / "merged.csv"

        write_dataset_csv(old_path, [_row("a.jpg")])
        write_dataset_csv(new_path, [_row("b.jpg")])

        merge_datasets(old_path, new_path, out_path)

        assert set(pd.read_csv(out_path)["image_name"]) == {"a.jpg", "b.jpg"}


# ---------------------------------------------------------------------------
# CLI smoke — run_merge error path
# ---------------------------------------------------------------------------


def test_run_merge_by_time_missing_column_exits(tmp_path: Path) -> None:
    """A merge-logic error propagates to the CLI boundary."""
    from cveta2.commands.merge import run_merge

    old_path = tmp_path / "old.csv"
    new_path = tmp_path / "new.csv"
    out_path = tmp_path / "merged.csv"

    no_time = _row("a.jpg")
    del no_time["task_updated_date"]
    write_dataset_csv(old_path, [dict(no_time)])
    write_dataset_csv(new_path, [dict(no_time)])

    args = make_args(
        old=str(old_path),
        new=str(new_path),
        output=str(out_path),
        deleted=None,
        by_time=True,
    )

    with pytest.raises(Cveta2Error):
        run_merge(args)

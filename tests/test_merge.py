"""Unit tests for merge: split propagation, by-time resolution, and I/O."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest
from loguru import logger

from cveta2.commands.merge import (
    _merge_datasets,
    _propagate_splits,
    _read_deleted_names,
    _resolve_by_time,
)

if TYPE_CHECKING:
    import argparse
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
) -> dict[str, str | float | None]:
    d: dict[str, str | float | None] = {
        "image_name": image,
        "instance_shape": "box",
        "instance_label": label,
        "bbox_x_tl": 0.0,
        "bbox_y_tl": 0.0,
        "bbox_x_br": 1.0,
        "bbox_y_br": 1.0,
        "split": split,
    }
    if task_updated_date is not None:
        d["task_updated_date"] = task_updated_date
    return d


def _df(rows: list[dict[str, str | float | None]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=[*_REQUIRED, "split"])
    return pd.DataFrame(rows)


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

    def test_no_propagation_when_old_has_no_split_column(self) -> None:
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

        messages: list[str] = []
        handler_id = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
        try:
            result = _propagate_splits(merged, old, new, {"a.jpg"})
        finally:
            logger.remove(handler_id)

        assert pd.isna(result["split"].iloc[0])
        assert any("нет данных split" in m for m in messages)

    def test_no_propagation_when_old_splits_all_null(self) -> None:
        """Warning emitted when old has split column but all values are NaN."""
        old = _df([_row("a.jpg", split=None)])
        new = _df([_row("a.jpg")])
        merged = new.copy()

        messages: list[str] = []
        handler_id = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
        try:
            _propagate_splits(merged, old, new, {"a.jpg"})
        finally:
            logger.remove(handler_id)

        assert any("нет данных split" in m for m in messages)

    def test_conflict_warning_when_both_have_split(self) -> None:
        """Warning emitted when both old and new have non-null split for same image."""
        old = _df([_row("a.jpg", split="train")])
        new = _df([_row("a.jpg", split="test")])
        merged = new.copy()

        messages: list[str] = []
        handler_id = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
        try:
            _propagate_splits(merged, old, new, {"a.jpg"})
        finally:
            logger.remove(handler_id)

        assert any("split задан в обоих датасетах" in m for m in messages)

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

    def test_no_split_in_old_warns(self) -> None:
        """Warning is logged when old dataset has no split data."""
        old = _df([_row("a.jpg")])
        new = _df([_row("a.jpg")])

        messages: list[str] = []
        handler_id = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
        try:
            _merge_datasets(old, new, set())
        finally:
            logger.remove(handler_id)

        assert any("нет данных split" in m for m in messages)

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
) -> dict[str, str | float | None]:
    """Row helper that always includes task_updated_date."""
    d = _row(image, label=label, split=split)
    d["task_updated_date"] = date
    return d


def _tdf(rows: list[dict[str, str | float | None]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=[*_REQUIRED, "split", "task_updated_date"])
    return pd.DataFrame(rows)


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
        csv_path = tmp_path / "deleted.csv"
        csv_path.write_text("image_name\na.jpg\nb.jpg\na.jpg\n", encoding="utf-8")

        result = _read_deleted_names(csv_path)

        assert result == {"a.jpg", "b.jpg"}

    def test_legacy_plain_text_format(self, tmp_path: Path) -> None:
        txt_path = tmp_path / "deleted.txt"
        txt_path.write_text("a.jpg\nb.jpg\n  \nc.jpg\n", encoding="utf-8")

        result = _read_deleted_names(txt_path)

        assert result == {"a.jpg", "b.jpg", "c.jpg"}

    def test_missing_file_exits(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.csv"

        with pytest.raises(SystemExit):
            _read_deleted_names(missing)


# ---------------------------------------------------------------------------
# I/O helpers — _read_dataset_csv (merge wrapper)
# ---------------------------------------------------------------------------


class TestReadDatasetCsvMerge:
    """Tests for _read_dataset_csv validation in merge context."""

    def test_by_time_without_time_column_exits(self, tmp_path: Path) -> None:
        from cveta2.commands.merge import _read_dataset_csv

        csv_path = tmp_path / "dataset.csv"
        cols = [*_REQUIRED, "split"]
        csv_path.write_text(",".join(cols) + "\n", encoding="utf-8")

        with pytest.raises(SystemExit):
            _read_dataset_csv(csv_path, by_time=True)

    def test_missing_required_columns_exits(self, tmp_path: Path) -> None:
        from cveta2.commands.merge import _read_dataset_csv

        csv_path = tmp_path / "dataset.csv"
        csv_path.write_text("image_name,split\na.jpg,train\n", encoding="utf-8")

        with pytest.raises(SystemExit):
            _read_dataset_csv(csv_path, by_time=False)

    def test_valid_csv_without_time_column_ok(self, tmp_path: Path) -> None:
        from cveta2.commands.merge import _read_dataset_csv

        csv_path = tmp_path / "dataset.csv"
        row = _row("a.jpg")
        df = pd.DataFrame([row])
        df.to_csv(csv_path, index=False, encoding="utf-8")

        result = _read_dataset_csv(csv_path, by_time=False)

        assert len(result) == 1


# ---------------------------------------------------------------------------
# CLI — run_merge
# ---------------------------------------------------------------------------


class TestRunMerge:
    """Tests for run_merge with real temp files."""

    def _write_csv(self, path: Path, rows: list[dict[str, str | float | None]]) -> None:
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")

    def test_basic_merge_output(self, tmp_path: Path) -> None:
        from cveta2.commands.merge import run_merge

        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"

        self._write_csv(old_path, [_row("a.jpg", split="train")])
        self._write_csv(new_path, [_row("a.jpg"), _row("b.jpg")])

        args = _make_args(
            old=str(old_path),
            new=str(new_path),
            output=str(out_path),
            deleted=None,
            by_time=False,
        )
        run_merge(args)

        result = pd.read_csv(out_path)
        names = set(result["image_name"])
        assert names == {"a.jpg", "b.jpg"}
        a_split = result.loc[result["image_name"] == "a.jpg", "split"].iloc[0]
        assert a_split == "train"

    def test_merge_with_deleted(self, tmp_path: Path) -> None:
        from cveta2.commands.merge import run_merge

        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        del_path = tmp_path / "deleted.csv"
        out_path = tmp_path / "merged.csv"

        self._write_csv(old_path, [_row("a.jpg"), _row("b.jpg")])
        self._write_csv(new_path, [_row("a.jpg"), _row("c.jpg")])
        del_path.write_text("image_name\na.jpg\n", encoding="utf-8")

        args = _make_args(
            old=str(old_path),
            new=str(new_path),
            output=str(out_path),
            deleted=str(del_path),
            by_time=False,
        )
        run_merge(args)

        result = pd.read_csv(out_path)
        names = set(result["image_name"])
        assert "a.jpg" not in names
        assert names == {"b.jpg", "c.jpg"}

    def test_merge_by_time(self, tmp_path: Path) -> None:
        from cveta2.commands.merge import run_merge

        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"

        self._write_csv(
            old_path,
            [_trow("a.jpg", date=_T_NEW, label="old_label")],
        )
        self._write_csv(
            new_path,
            [_trow("a.jpg", date=_T_OLD, label="new_label")],
        )

        args = _make_args(
            old=str(old_path),
            new=str(new_path),
            output=str(out_path),
            deleted=None,
            by_time=True,
        )
        run_merge(args)

        result = pd.read_csv(out_path)
        assert result.iloc[0]["instance_label"] == "old_label"

    def test_by_time_missing_column_exits(self, tmp_path: Path) -> None:
        from cveta2.commands.merge import run_merge

        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"

        self._write_csv(old_path, [_row("a.jpg")])
        self._write_csv(new_path, [_row("a.jpg")])

        args = _make_args(
            old=str(old_path),
            new=str(new_path),
            output=str(out_path),
            deleted=None,
            by_time=True,
        )

        with pytest.raises(SystemExit):
            run_merge(args)


# ---------------------------------------------------------------------------
# Helpers for CLI tests
# ---------------------------------------------------------------------------


def _make_args(
    *,
    old: str,
    new: str,
    output: str,
    deleted: str | None,
    by_time: bool,
) -> argparse.Namespace:
    import argparse

    return argparse.Namespace(
        old=old,
        new=new,
        output=output,
        deleted=deleted,
        by_time=by_time,
    )

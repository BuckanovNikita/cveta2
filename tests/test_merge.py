"""Unit tests for _merge_datasets with split propagation."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from cveta2.commands.merge import _merge_datasets, _propagate_splits

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
) -> dict[str, str | float | None]:
    return {
        "image_name": image,
        "instance_shape": "box",
        "instance_label": label,
        "bbox_x_tl": 0.0,
        "bbox_y_tl": 0.0,
        "bbox_x_br": 1.0,
        "bbox_y_br": 1.0,
        "split": split,
    }


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

"""Split carry-over from a published parent, keyed by image name."""

from typing import TYPE_CHECKING

import pandas as pd

from cveta2.domain.bundle.splits import changed_splits, prefill_splits, published_splits

if TYPE_CHECKING:
    from cveta2.domain.models import Split


def frame(*rows: tuple[object, object]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["image_name", "split"], dtype=object)


def test_published_splits_skips_conflicting_names() -> None:
    parent = frame(("a.jpg", "train"), ("b.jpg", "val"), ("c.jpg", "train"), ("c.jpg", "val"))
    assert published_splits(parent) == {"a.jpg": "train", "b.jpg": "val"}


def test_published_splits_ignores_rows_without_a_valid_split() -> None:
    parent = frame(("a.jpg", "train"), ("a.jpg", ""), ("b.jpg", "holdout"), ("", "val"))
    assert published_splits(parent) == {"a.jpg": "train"}
    assert published_splits(pd.DataFrame({"image_name": ["a.jpg"]})) == {}


def test_prefill_fills_only_empty_cells_of_published_images() -> None:
    current = frame(("a.jpg", ""), ("a.jpg", float("nan")), ("b.jpg", "test"), ("d.jpg", ""))
    original = current.copy(deep=True)
    filled, count = prefill_splits(current, {"a.jpg": "train", "b.jpg": "val"})
    assert filled["split"].tolist() == ["train", "train", "test", ""]
    assert count == 1
    pd.testing.assert_frame_equal(current, original)


def test_prefill_keeps_invalid_values_and_duplicate_indices() -> None:
    current = pd.DataFrame(
        {"image_name": ["a.jpg", "a.jpg", "b.jpg"], "split": ["holdout", "", ""]},
        index=[7, 7, 7],
        dtype=object,
    )
    filled, count = prefill_splits(current, {"a.jpg": "val", "b.jpg": "train"})
    # ``holdout`` disagrees with the published ``val``, so ``a.jpg`` stays as the user wrote it.
    assert filled["split"].tolist() == ["holdout", "", "train"]
    assert filled.index.tolist() == [7, 7, 7]
    assert count == 1


def test_prefill_fills_an_image_whose_other_cells_agree_with_the_parent() -> None:
    current = frame(("a.jpg", "val"), ("a.jpg", ""), ("b.jpg", ""), ("b.jpg", float("nan")))
    filled, count = prefill_splits(current, {"a.jpg": "val", "b.jpg": "train"})
    assert filled["split"].tolist() == ["val", "val", "train", "train"]
    assert count == 2


def test_prefill_leaves_an_image_whose_other_cells_disagree_with_the_parent() -> None:
    current = frame(("a.jpg", "train"), ("a.jpg", ""), ("a.jpg", "val"), ("b.jpg", ""))
    filled, count = prefill_splits(current, {"a.jpg": "val", "b.jpg": "test"})
    assert filled["split"].tolist() == ["train", "", "val", "test"]
    assert count == 1


def test_prefill_fills_a_float_split_column() -> None:
    current = pd.DataFrame({"image_name": ["a.jpg", "b.jpg"], "split": [float("nan"), float("nan")]})
    filled, count = prefill_splits(current, {"a.jpg": "val"})
    assert filled["split"].iloc[0] == "val"
    assert count == 1


def test_prefill_adds_missing_split_column() -> None:
    current = pd.DataFrame({"image_name": ["a.jpg", "d.jpg"]}, dtype=object)
    filled, count = prefill_splits(current, {"a.jpg": "train"})
    assert filled["split"].tolist() == ["train", ""]
    assert count == 1
    assert "split" not in current


def test_prefill_without_image_names_changes_nothing() -> None:
    filled, count = prefill_splits(pd.DataFrame({"split": ["", "train"]}, dtype=object), {"a.jpg": "val"})
    assert filled["split"].tolist() == ["", "train"]
    assert count == 0
    filled, count = prefill_splits(pd.DataFrame({"other": ["x"]}, dtype=object), {"a.jpg": "val"})
    assert filled["split"].tolist() == [""]
    assert count == 0


def test_changed_splits_lists_published_images_with_another_split() -> None:
    current = frame(("a.jpg", "train"), ("b.jpg", "test"), ("b.jpg", ""), ("c.jpg", "val"), ("e.jpg", "test"))
    published: dict[str, Split] = {"a.jpg": "train", "b.jpg": "val", "c.jpg": "test", "d.jpg": "val"}
    assert changed_splits(current, published) == (("b.jpg", "val", "test"), ("c.jpg", "test", "val"))
    assert changed_splits(pd.DataFrame({"image_name": ["b.jpg"]}), published) == ()

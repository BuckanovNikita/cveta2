"""Behavioral contracts for stable split, overlap and comparison policies."""

import pandas as pd
import pytest

from cveta2.domain.managed.models import ManagedError, OverlapDecision
from cveta2.domain.managed.policies import (
    compare_frames,
    propagate_splits,
    rebuild_assignments,
    resolve_overlaps,
    split_collisions,
    split_conflicts,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "image_name": ["a.jpg", "b.jpg", "c.jpg"],
            "image_path": ["/images/a.jpg", "/images/b.jpg", "/images/c.jpg"],
            "instance_label": ["helmet", "person", ""],
            "split": ["wrong", "wrong", "wrong"],
            "source_id": ["main", "main", "imported"],
        }
    )


@pytest.mark.parametrize(
    ("frame", "hashes", "published"),
    [
        (pd.DataFrame({"image_path": ["/a.jpg"]}), {"/a.jpg": "a"}, {"a": "other"}),
        (
            pd.DataFrame([["/a.jpg", "/b.jpg"]], columns=["image_path", "image_path"]),
            {},
            {},
        ),
    ],
)
def test_propagate_splits_rejects_duplicate_columns_and_invalid_published_splits(
    frame: pd.DataFrame, hashes: dict[str, str], published: dict[str, str]
) -> None:
    """No ambiguous identity or invalid published split is silently propagated."""
    with pytest.raises(ManagedError):
        propagate_splits(frame, hashes, published)


FRAME = pd.DataFrame(
    {
        "image_name": ["a.png", "a.png", "b.png", "new.png"],
        "image_path": ["/i/a", "/i/a", "/i/b", "/i/new"],
        "split": ["val", "val", "", ""],
    }
)
HASHES = {"/i/a": "ha", "/i/b": "hb", "/i/new": "hn"}


def test_propagate_splits_writes_published_split_and_counts_rows() -> None:
    result, replaced = propagate_splits(FRAME, HASHES, {"ha": "train", "hb": "test"})
    assert result["split"].tolist() == ["train", "train", "test", ""]
    assert replaced == 3
    assert FRAME["split"].tolist() == ["val", "val", "", ""]  # input untouched


def test_propagate_splits_leaves_a_row_without_a_hash_unchanged() -> None:
    result, replaced = propagate_splits(FRAME, {"/i/b": "hb"}, {"ha": "train", "hb": "test"})
    assert result["split"].tolist() == ["val", "val", "test", ""]
    assert replaced == 1


def test_propagate_splits_adds_an_empty_split_column() -> None:
    result, replaced = propagate_splits(FRAME.drop(columns="split"), HASHES, {})
    assert result["split"].tolist() == ["", "", "", ""]
    assert replaced == 0


def test_rebuild_assignments_keeps_removed_images_and_skips_empty_splits() -> None:
    assert rebuild_assignments(FRAME, HASHES, {"ha": "train", "gone": "test"}) == {"gone": "test", "ha": "val"}


def test_rebuild_assignments_rejects_an_unknown_split() -> None:
    with pytest.raises(ManagedError, match=r"Invalid split for image: a\.png"):
        rebuild_assignments(FRAME.assign(split="holdout"), HASHES, {})


def _overlap() -> tuple[pd.DataFrame, dict[str, str]]:
    frame = pd.DataFrame(
        {
            "image_name": ["a.jpg", "a.jpg", "b.jpg"],
            "image_path": ["/one/a.jpg", "/two/a.jpg", "/two/b.jpg"],
            "source_id": ["first", "second", "second"],
            "instance_label": ["one", "two", "three"],
        }
    )
    return frame, {"/one/a.jpg": "same", "/two/a.jpg": "same", "/two/b.jpg": "other"}


def test_overlapping_content_requires_exact_membership_and_explicit_source() -> None:
    """A decision is valid only for the sources the user reviewed."""
    frame, hashes = _overlap()
    with pytest.raises(ManagedError, match="overlap"):
        resolve_overlaps(frame, hashes, {})
    with pytest.raises(ManagedError, match="membership"):
        resolve_overlaps(frame, hashes, {"same": OverlapDecision(source="first", members=["first"])})
    original = frame.copy(deep=True)
    result = resolve_overlaps(
        frame,
        hashes,
        {"same": OverlapDecision(source="first", members=["first", "second"])},
    )
    assert result["instance_label"].tolist() == ["one", "three"]
    pd.testing.assert_frame_equal(frame, original)


def test_overlap_exclusion_and_stale_decision_after_source_removal() -> None:
    """Exclusion removes all contributing rows and stale membership blocks."""
    frame, hashes = _overlap()
    decision = OverlapDecision(source=None, members=["first", "second"])
    result = resolve_overlaps(frame, hashes, {"same": decision})
    assert result["image_name"].tolist() == ["b.jpg"]
    with pytest.raises(ManagedError, match="membership"):
        resolve_overlaps(frame.iloc[[0, 2]], hashes, {"same": decision})


def test_filename_conflicts_are_not_resolved_by_source_selection() -> None:
    """Same basenames with different bytes must be corrected before training."""
    frame, hashes = _overlap()
    hashes["/two/a.jpg"] = "different"
    with pytest.raises(ManagedError, match="filename"):
        resolve_overlaps(frame, hashes, {})


def test_unmapped_transformed_rows_are_preserved_without_invented_sources() -> None:
    """Lack of lineage remains honest instead of being guessed from filenames."""
    frame = _frame().drop(columns="source_id")
    hashes = {path: path for path in frame["image_path"]}
    result = resolve_overlaps(frame, hashes, {})
    pd.testing.assert_frame_equal(result, frame)


def test_overlap_cannot_silently_attribute_unmapped_rows() -> None:
    """Choosing one owner cannot make a lineage decision for unknown rows."""
    frame, hashes = _overlap()
    frame.loc[3] = ["a.jpg", "/third/a.jpg", "", "unknown"]
    hashes["/third/a.jpg"] = "same"
    with pytest.raises(ManagedError, match="unmapped"):
        resolve_overlaps(
            frame,
            hashes,
            {"same": OverlapDecision(source="first", members=["first", "second"])},
        )


def test_compare_reports_multiset_row_and_image_class_split_changes() -> None:
    """Duplicate counts, additions/removals and retained-image edits are visible."""
    old = pd.DataFrame(
        {
            "image_name": ["a.jpg", "a.jpg", "b.jpg"],
            "instance_label": ["cat", "cat", "dog"],
            "split": ["train", "train", "val"],
        }
    )
    new = pd.DataFrame(
        {
            "split": ["test", "train"],
            "instance_label": ["fox", "bird"],
            "image_name": ["a.jpg", "c.jpg"],
        }
    )
    summary = compare_frames(old, new)
    assert summary["rows"] == {
        "old": 3,
        "new": 2,
        "added": 2,
        "removed": 3,
        "unchanged": 0,
    }
    assert summary["images"] == {
        "added": ["c.jpg"],
        "removed": ["b.jpg"],
        "changed": ["a.jpg"],
    }
    assert summary["classes"] == {"added": ["bird", "fox"], "removed": ["cat", "dog"]}
    assert summary["splits"]["old"] == {"train": 1, "val": 1}
    assert summary["splits"]["new"] == {"test": 1, "train": 1}
    assert compare_frames(old, old.iloc[::-1])["rows"]["unchanged"] == 3


def test_compare_normalizes_missing_cells_and_rejects_opaque_values() -> None:
    """Missing lexical cells compare consistently; unsupported values fail clearly."""
    old = pd.DataFrame({"image_name": ["a.jpg"], "label": [None]})
    new = pd.DataFrame({"label": [float("nan")], "image_name": ["a.jpg"]})
    assert compare_frames(old, new)["rows"]["unchanged"] == 1
    old = pd.DataFrame({"image_name": ["a.jpg"], "opaque": [object()]})
    with pytest.raises(ManagedError, match="Unsupported"):
        compare_frames(old, new)


def test_split_collisions_go_by_content() -> None:
    frame = pd.DataFrame(
        {
            "image_name": ["a.png", "copy.png", "b.png", "b.png"],
            "image_path": ["/i/a", "/i/copy", "/i/b", "/i/b"],
            "split": ["train", "val", "train", ""],
        }
    )
    assert split_collisions(frame, {"/i/a": "h", "/i/copy": "h", "/i/b": "hb"}) == ("a.png", "copy.png")


def test_split_collisions_fall_back_to_the_path_and_skip_unhashed_rows() -> None:
    frame = pd.DataFrame({"image_path": ["/i/a", "/i/c", "/i/x"], "split": ["train", "val", "val"]})
    assert split_collisions(frame, {"/i/a": "h", "/i/c": "h"}) == ("/i/a", "/i/c")


def test_split_conflicts_name_images_whose_published_split_moved() -> None:
    assert split_conflicts(FRAME, HASHES, {"ha": "train", "hb": "test"}) == ("a.png",)

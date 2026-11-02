"""Behavioral contracts for stable split, overlap and comparison policies."""

from collections import Counter

import pandas as pd
import pytest

from cveta2.domain.managed.models import ManagedError, OverlapDecision, SplitPolicy
from cveta2.domain.managed.policies import (
    assign_splits,
    compare_frames,
    resolve_overlaps,
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


def test_split_defaults_replace_input_and_stay_stable_across_order_and_versions() -> (
    None
):
    """Adding or removing other images cannot rebalance published assignments."""
    frame = _frame()
    original = frame.copy(deep=True)
    hashes = dict(zip(frame["image_path"], ["aaa", "bbb", "ccc"], strict=True))
    split, assignments = assign_splits(frame, SplitPolicy(), hashes)
    reverse, reverse_assignments = assign_splits(
        frame.iloc[::-1], SplitPolicy(), hashes
    )
    assert assignments == reverse_assignments
    assert dict(zip(split["image_name"], split["split"], strict=True)) == dict(
        zip(reverse["image_name"], reverse["split"], strict=True)
    )
    pd.testing.assert_frame_equal(frame, original)
    preserved = dict(assignments, removed="test")
    next_frame = frame.iloc[:1].copy()
    changed_seed, next_assignments = assign_splits(
        next_frame, SplitPolicy(seed=100), hashes, preserved
    )
    assert next_assignments == preserved
    assert changed_seed["split"].iloc[0] == split["split"].iloc[0]


def test_split_groups_identical_content_and_approximates_default_targets() -> None:
    """Hash assignment acts per content rather than per source row or filename."""
    frame = pd.DataFrame({"image_path": [f"/images/{n}.jpg" for n in range(10000)]})
    hashes = {path: str(n) for n, path in enumerate(frame["image_path"])}
    split, assignments = assign_splits(frame, SplitPolicy(), hashes)
    counts = Counter(split["split"])
    assert 0.57 < counts["train"] / len(frame) < 0.63
    assert 0.17 < counts["val"] / len(frame) < 0.23
    assert 0.17 < counts["test"] / len(frame) < 0.23
    doubled = pd.DataFrame({"image_path": ["/a.jpg", "/b.jpg"]})
    same, _ = assign_splits(
        doubled, SplitPolicy(), {"/a.jpg": "same", "/b.jpg": "same"}
    )
    assert len(set(same["split"])) == 1
    assert len(assignments) == len(frame)


@pytest.mark.parametrize(
    ("frame", "hashes", "previous"),
    [
        (pd.DataFrame({"image_path": ["/a.jpg"]}), {}, {}),
        (pd.DataFrame({"image_path": [""]}), {"": "a"}, {}),
        (pd.DataFrame({"image_path": ["/a.jpg"]}), {"/a.jpg": ""}, {}),
        (pd.DataFrame({"image_path": ["/a.jpg"]}), {"/a.jpg": "a"}, {"a": "other"}),
        (
            pd.DataFrame([["/a.jpg", "/b.jpg"]], columns=["image_path", "image_path"]),
            {},
            {},
        ),
    ],
)
def test_split_rejects_ambiguous_or_missing_identity(
    frame: pd.DataFrame, hashes: dict[str, str], previous: dict[str, str]
) -> None:
    """No missing digest or invalid published split is silently assigned."""
    with pytest.raises(ManagedError):
        assign_splits(frame, SplitPolicy(), hashes, previous)


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
        resolve_overlaps(
            frame, hashes, {"same": OverlapDecision(source="first", members=["first"])}
        )
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

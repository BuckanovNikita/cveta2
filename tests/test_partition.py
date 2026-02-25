"""Unit tests for partition_annotations_df (dataset / obsolete / in_progress)."""

from __future__ import annotations

import pandas as pd

from cveta2.dataset_partition import partition_annotations_df
from cveta2.models import DeletedImage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal columns required by partition_annotations_df
_COLS = ["image_name", "task_id", "task_updated_date", "task_status"]


def _row(
    image: str,
    task_id: int,
    updated: str,
    status: str = "completed",
) -> dict[str, str | int]:
    return {
        "image_name": image,
        "task_id": task_id,
        "task_updated_date": updated,
        "task_status": status,
    }


def _df(rows: list[dict[str, str | int]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_COLS)
    return pd.DataFrame(rows)


def _deleted(
    image: str,
    task_id: int,
    updated: str,
    status: str = "completed",
) -> DeletedImage:
    return DeletedImage(
        task_id=task_id,
        task_name=f"task-{task_id}",
        task_status=status,
        task_updated_date=updated,
        frame_id=0,
        image_name=image,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_dataframe() -> None:
    """Empty DataFrame produces empty PartitionResult."""
    result = partition_annotations_df(_df([]), [])

    assert len(result.dataset) == 0
    assert len(result.obsolete) == 0
    assert len(result.in_progress) == 0
    assert result.deleted_images == []


def test_single_completed_task() -> None:
    """One completed task with 3 images, no deletions -- all go to dataset."""
    rows = [
        _row("a.jpg", 1, "2026-01-02T00:00:00"),
        _row("b.jpg", 1, "2026-01-02T00:00:00"),
        _row("c.jpg", 1, "2026-01-02T00:00:00"),
    ]
    result = partition_annotations_df(_df(rows), [])

    assert len(result.dataset) == 3
    assert len(result.obsolete) == 0
    assert len(result.in_progress) == 0
    assert result.deleted_images == []


def test_single_in_progress_task() -> None:
    """One annotation-status task -- all rows go to in_progress."""
    rows = [
        _row("a.jpg", 1, "2026-01-02T00:00:00", status="annotation"),
        _row("b.jpg", 1, "2026-01-02T00:00:00", status="annotation"),
    ]
    result = partition_annotations_df(_df(rows), [])

    assert len(result.dataset) == 0
    assert len(result.obsolete) == 0
    assert len(result.in_progress) == 2
    assert result.deleted_images == []


def test_deleted_image_latest_task() -> None:
    """Image deleted in a newer task -- annotation row goes to obsolete."""
    rows = [
        _row("a.jpg", 1, "2026-01-01T00:00:00"),  # older completed
    ]
    deleted = [
        _deleted("a.jpg", 2, "2026-01-02T00:00:00"),  # newer deletion
    ]
    result = partition_annotations_df(_df(rows), deleted)

    assert len(result.dataset) == 0
    assert len(result.obsolete) == 1
    assert result.obsolete["image_name"].iloc[0] == "a.jpg"
    assert [d.image_name for d in result.deleted_images] == ["a.jpg"]


def test_deleted_image_older_task() -> None:
    """Image deleted in an older task -- annotation row stays in dataset."""
    rows = [
        _row("a.jpg", 2, "2026-01-02T00:00:00"),  # newer completed
    ]
    deleted = [
        _deleted("a.jpg", 1, "2026-01-01T00:00:00"),  # older deletion
    ]
    result = partition_annotations_df(_df(rows), deleted)

    assert len(result.dataset) == 1
    assert len(result.obsolete) == 0
    assert result.deleted_images == []


def test_deleted_then_restored() -> None:
    """Image deleted in T1, then re-annotated in T2 (newer).

    The latest task for the image is T2 (annotation, not deletion),
    so the image is NOT treated as deleted.  T2 annotations go to
    dataset, T1 annotations go to obsolete, deleted_names is empty.
    """
    rows = [
        _row("a.jpg", 1, "2026-01-01T00:00:00"),  # T1 completed (older)
        _row("a.jpg", 2, "2026-01-03T00:00:00"),  # T2 completed (newer)
    ]
    deleted = [
        _deleted("a.jpg", 1, "2026-01-02T00:00:00"),  # deletion from T1
    ]
    result = partition_annotations_df(_df(rows), deleted)

    # T2 (newest) is an annotation row, not a deletion -> image is alive
    assert result.deleted_images == []
    # T2 row in dataset (latest completed)
    assert len(result.dataset) == 1
    assert result.dataset["task_id"].iloc[0] == 2
    # T1 row in obsolete (older completed)
    assert len(result.obsolete) == 1
    assert result.obsolete["task_id"].iloc[0] == 1


def test_multiple_completed_tasks_latest_wins() -> None:
    """Same image in 2 completed tasks -- latest goes to dataset, older to obsolete."""
    rows = [
        _row("a.jpg", 1, "2026-01-01T00:00:00"),  # older
        _row("a.jpg", 2, "2026-01-02T00:00:00"),  # newer
    ]
    result = partition_annotations_df(_df(rows), [])

    assert len(result.dataset) == 1
    assert result.dataset["task_id"].iloc[0] == 2
    assert len(result.obsolete) == 1
    assert result.obsolete["task_id"].iloc[0] == 1


def test_completed_and_in_progress_split() -> None:
    """Same image: completed task + annotation task -- split correctly."""
    rows = [
        _row("a.jpg", 1, "2026-01-01T00:00:00", status="completed"),
        _row("a.jpg", 2, "2026-01-02T00:00:00", status="annotation"),
    ]
    result = partition_annotations_df(_df(rows), [])

    assert len(result.dataset) == 1
    assert result.dataset["task_id"].iloc[0] == 1
    assert len(result.in_progress) == 1
    assert result.in_progress["task_id"].iloc[0] == 2
    assert len(result.obsolete) == 0


def test_image_only_in_deleted_registry() -> None:
    """Image exists only in deleted_images, not in df -- appears in deleted_names."""
    rows = [
        _row("a.jpg", 1, "2026-01-01T00:00:00"),
    ]
    deleted = [
        _deleted("phantom.jpg", 2, "2026-01-02T00:00:00"),  # not in df
    ]
    result = partition_annotations_df(_df(rows), deleted)

    assert len(result.dataset) == 1  # a.jpg unaffected
    # phantom.jpg has no df rows, but is tracked in deleted_images
    assert "phantom.jpg" in [d.image_name for d in result.deleted_images]


def test_all_images_deleted() -> None:
    """All images deleted in latest task -- everything to obsolete."""
    rows = [
        _row("a.jpg", 1, "2026-01-01T00:00:00"),
        _row("b.jpg", 1, "2026-01-01T00:00:00"),
    ]
    deleted = [
        _deleted("a.jpg", 2, "2026-01-02T00:00:00"),
        _deleted("b.jpg", 2, "2026-01-02T00:00:00"),
    ]
    result = partition_annotations_df(_df(rows), deleted)

    assert len(result.dataset) == 0
    assert len(result.obsolete) == 2
    assert len(result.in_progress) == 0
    assert sorted(d.image_name for d in result.deleted_images) == ["a.jpg", "b.jpg"]


def test_mixed_partition() -> None:
    """5 images across different scenarios produce correct three-way split.

    - img_ds1.jpg, img_ds2.jpg: completed in latest task -> dataset
    - img_stale.jpg: completed in older task, newer completed in task 2 -> obsolete
    - img_ip.jpg: annotation status -> in_progress
    - img_del.jpg: deleted in latest task -> obsolete + deleted_images
    """
    rows = [
        # Two images only in the latest completed task -> dataset
        _row("img_ds1.jpg", 2, "2026-01-02T00:00:00"),
        _row("img_ds2.jpg", 2, "2026-01-02T00:00:00"),
        # Stale: older completed task for same image -> obsolete
        _row("img_stale.jpg", 1, "2026-01-01T00:00:00"),
        _row("img_stale.jpg", 2, "2026-01-02T00:00:00"),
        # In-progress
        _row("img_ip.jpg", 3, "2026-01-03T00:00:00", status="annotation"),
        # Deleted: has an annotation row but deletion is newer
        _row("img_del.jpg", 1, "2026-01-01T00:00:00"),
    ]
    deleted = [
        _deleted("img_del.jpg", 4, "2026-01-04T00:00:00"),
    ]

    result = partition_annotations_df(_df(rows), deleted)

    # Dataset: img_ds1, img_ds2, img_stale (from task 2)
    dataset_names = set(result.dataset["image_name"])
    assert dataset_names == {"img_ds1.jpg", "img_ds2.jpg", "img_stale.jpg"}
    assert len(result.dataset) == 3

    # Obsolete: img_stale (from task 1) + img_del (annotation row)
    obsolete_images = list(result.obsolete["image_name"])
    assert "img_del.jpg" in obsolete_images
    # img_stale from task 1 is obsolete
    stale_obsolete = result.obsolete[result.obsolete["image_name"] == "img_stale.jpg"]
    assert len(stale_obsolete) == 1
    assert stale_obsolete["task_id"].iloc[0] == 1

    # In-progress
    assert len(result.in_progress) == 1
    assert result.in_progress["image_name"].iloc[0] == "img_ip.jpg"

    # Deleted images
    assert [d.image_name for d in result.deleted_images] == ["img_del.jpg"]


def test_deleted_image_with_annotations_in_same_task() -> None:
    """Bug: Image has annotations AND is marked deleted in same task with same date.

    This reproduces the bug where an image is marked as deleted in a task,
    but that task still contains annotation shapes for that image (before it
    was deleted). Both have the same task_updated_date, and the annotation
    wins because it appears first in the combined dataframe.

    Expected: The image should be marked as deleted and go to obsolete.
    Actual (bug): The image appears in dataset because annotation wins the tie.
    """
    rows = [
        # Earlier task with annotation
        _row("img.jpg", 1, "2026-01-01T00:00:00"),
        # Latest task has annotation for the image (before deletion)
        _row("img.jpg", 2, "2026-01-02T00:00:00"),
    ]
    deleted = [
        # Same task marks the image as deleted (same date as annotation)
        _deleted("img.jpg", 2, "2026-01-02T00:00:00"),
    ]
    result = partition_annotations_df(_df(rows), deleted)

    assert len(result.dataset) == 0, "Deleted image should not be in dataset"
    assert len(result.obsolete) == 2, "Both rows should be obsolete"
    assert "img.jpg" in [d.image_name for d in result.deleted_images], (
        "Image should be in deleted_images"
    )

"""Unit tests for partition_annotations_df (dataset / obsolete / in_progress)."""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from cveta2.domain.models import CSV_COLUMNS
from cveta2.domain.partition import completed_task_ids, partition_annotations_df
from tests.helpers import csv_row, make_deleted, make_df

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal columns required by partition_annotations_df
_COLS = ["image_name", "task_id", "task_updated_date", "job_stage", "job_state"]


def _row(
    image: str,
    task_id: int,
    updated: str,
    status: str = "completed",
) -> dict[str, object]:
    return csv_row(image, task_id=task_id, updated=updated, status=status)


def _df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return make_df(rows, columns=_COLS)


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


def test_deleted_record_carries_unfinished_task_into_legacy_annotation_rows() -> None:
    deleted = make_deleted("gone.jpg", task_id=7, updated="2026-09-04")
    deleted.task_completed = False
    annotations = _df([_row("kept.jpg", task_id=7, updated="2026-09-04")])

    result = partition_annotations_df(annotations, [deleted])

    assert result.dataset.empty
    assert result.in_progress["image_name"].tolist() == ["kept.jpg"]


def test_unknown_legacy_completion_is_independent_of_nullable_dtype() -> None:
    """Missing stage, state or both disqualify their task, including finished rows."""
    source = pd.DataFrame(
        [
            ("a.jpg", 1, "acceptance", "completed"),
            ("b.jpg", 1, pd.NA, "completed"),
            ("c.jpg", 2, "acceptance", "completed"),
            ("d.jpg", 2, "acceptance", pd.NA),
            ("e.jpg", 3, "acceptance", "completed"),
            ("f.jpg", 3, pd.NA, pd.NA),
            ("g.jpg", 4, "acceptance", "completed"),
        ],
        columns=["image_name", "task_id", "job_stage", "job_state"],
    )
    for dtype in ("object", "string"):
        frame = source.astype({"job_stage": dtype, "job_state": dtype})

        assert completed_task_ids(frame) == {4}
        result = partition_annotations_df(frame, [])
        assert result.dataset["image_name"].tolist() == ["g.jpg"]
        assert result.in_progress["image_name"].tolist() == [
            "a.jpg",
            "b.jpg",
            "c.jpg",
            "d.jpg",
            "e.jpg",
            "f.jpg",
        ]
        assert result.obsolete.empty


def test_nullable_explicit_completion_keeps_overrides_and_legacy_fallback() -> None:
    frame = pd.DataFrame(
        {
            "image_name": ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"],
            "task_id": [1, 1, 2, 3, 4],
            "job_stage": pd.Series(["acceptance", pd.NA, pd.NA, "acceptance", "acceptance"], dtype="string"),
            "job_state": pd.Series(["completed", pd.NA, pd.NA, "completed", "completed"], dtype="string"),
            "task_completed": pd.Series([pd.NA, pd.NA, True, False, pd.NA], dtype="boolean"),
        }
    )

    assert completed_task_ids(frame) == {2, 4}
    result = partition_annotations_df(frame, [])
    assert result.dataset["image_name"].tolist() == ["c.jpg", "e.jpg"]
    assert result.in_progress["image_name"].tolist() == ["a.jpg", "b.jpg", "d.jpg"]
    assert result.obsolete.empty


def test_empty_dataframe_keeps_deletions() -> None:
    """A frame without rows or columns still reports its deleted images.

    A task whose every frame is deleted and that carries no shapes yields
    zero annotation records, so the fetch builds a column-less frame. The
    early return used to drop the deletions with it, leaving deleted.csv
    empty although CVAT reported the frames deleted.
    """
    deleted = [
        make_deleted("a.jpg", 1, "2026-01-01T00:00:00"),
        make_deleted("a.jpg", 2, "2026-01-02T00:00:00"),
        make_deleted("b.jpg", 2, "2026-01-02T00:00:00"),
    ]
    result = partition_annotations_df(pd.DataFrame([]), deleted)

    assert [(d.image_name, d.task_id) for d in result.deleted_images] == [
        ("a.jpg", 2),
        ("b.jpg", 2),
    ]
    assert len(result.dataset) == 0
    assert len(result.obsolete) == 0
    assert len(result.in_progress) == 0


def test_empty_dataframe_keeps_column_order() -> None:
    """An empty frame that already has the CSV schema keeps it, in order.

    The three output frames become the CSV headers, so the schema must
    survive unsorted: ``reindex`` with an alphabetised union would write
    ``attributes`` first.
    """
    result = partition_annotations_df(pd.DataFrame([], columns=list(CSV_COLUMNS)), [])

    for frame in (result.dataset, result.obsolete, result.in_progress):
        assert list(frame.columns) == list(CSV_COLUMNS)
        assert len(frame) == 0
    assert result.deleted_images == []


# One record per annotation row or deletion: (image, task_id, job finished).
_Record = tuple[str, int, bool]
_RECORDS = st.tuples(st.sampled_from(["a.jpg", "b.jpg", "c.jpg"]), st.integers(1, 5), st.booleans())


def _expected_partition(
    rows: list[_Record], deletions: list[_Record]
) -> tuple[dict[str, set[int]], list[tuple[str, int]]]:
    """Specify the partition: row positions per part, and the deleted images.

    A task is complete when every row and deletion record of it is finished.
    Per image the highest task id is the latest, and a deletion wins a tie
    within its own task. A deleted image sends all its rows to obsolete;
    otherwise unfinished tasks go to in_progress, the latest completed task
    to dataset and older completed tasks to obsolete.
    """
    unfinished = {task for _, task, done in rows + deletions if not done}
    latest: dict[str, tuple[int, bool]] = {}
    for records, is_deletion in ((rows, False), (deletions, True)):
        for image, task, _ in records:
            latest[image] = max(latest.get(image, (0, False)), (task, is_deletion))
    deleted = {image: task for image, (task, gone) in latest.items() if gone}
    newest_completed = {
        image: max(t for i, t, _ in rows if i == image and t not in unfinished)
        for image, _, _ in rows
        if any(i == image and t not in unfinished for i, t, _ in rows)
    }
    parts: dict[str, set[int]] = {
        "dataset": set(),
        "obsolete": set(),
        "in_progress": set(),
    }
    for position, (image, task, _) in enumerate(rows):
        if image in deleted:
            part = "obsolete"
        elif task in unfinished:
            part = "in_progress"
        elif task == newest_completed[image]:
            part = "dataset"
        else:
            part = "obsolete"
        parts[part].add(position)
    return parts, sorted(deleted.items())


def _status(done: bool) -> str:  # noqa: FBT001 - maps a drawn flag
    return "completed" if done else "annotation"


@given(
    rows=st.lists(_RECORDS, max_size=12),
    deletions=st.lists(_RECORDS, max_size=4),
)
# A deletion in the same task as the image's latest annotation wins the tie.
@example(rows=[("a.jpg", 1, True), ("a.jpg", 2, True)], deletions=[("a.jpg", 2, True)])
# Deleted in task 2, re-annotated later in task 5: the image is alive again.
@example(
    rows=[("a.jpg", 1, True), ("b.jpg", 3, True), ("a.jpg", 5, True)],
    deletions=[("a.jpg", 2, True)],
)
# Duplicate deletion records collapse into one deleted image.
@example(rows=[("a.jpg", 1, True)], deletions=[("a.jpg", 2, True)] * 2)
# An unfinished job seen only through a deletion record holds its task back.
@example(rows=[("a.jpg", 1, True)], deletions=[("gone.jpg", 1, False)])
def test_partition_matches_specification(rows: list[_Record], deletions: list[_Record]) -> None:
    """Every row lands in exactly the part the specification assigns.

    Task dates are deliberately reversed against task ids: only the id orders
    tasks, so a project-wide label edit that rewrites every date cannot
    scramble the partition.
    """
    frame = _df(
        [_row(image, task, f"2026-01-{31 - task:02d}T00:00:00", _status(done)) for image, task, done in rows]
    ).assign(row=range(len(rows)))
    records = [
        make_deleted(image, task, f"2026-01-{31 - task:02d}T00:00:00", _status(done)) for image, task, done in deletions
    ]

    result = partition_annotations_df(frame, records)

    parts, deleted = _expected_partition(rows, deletions)
    assert {
        "dataset": set(result.dataset["row"]),
        "obsolete": set(result.obsolete["row"]),
        "in_progress": set(result.in_progress["row"]),
    } == parts
    assert len(result.dataset) + len(result.obsolete) + len(result.in_progress) == len(rows)
    assert [(d.image_name, d.task_id) for d in result.deleted_images] == deleted


def test_deletion_wins_tie_in_a_frame_too_large_for_a_stable_sort() -> None:
    """Same-timestamp deletion still wins once the frame outgrows insertion sort.

    The partition property covers the same rule on small frames, where every
    sort algorithm happens to preserve input order and so cannot detect a lost
    tie-break. Fourteen unrelated rows push the
    combined frame past that threshold, where an implicitly-stable sort starts
    reordering equal keys and the deletion silently loses.
    """
    tie = "2026-03-02T10:00:00"
    rows = [
        _row("contested.jpg", 1, tie),
        _row("contested.jpg", 2, tie),
    ]
    rows += [_row(f"filler{i % 5}.jpg", 10 + i, f"2026-03-{(i % 3) + 1:02d}T10:00:00") for i in range(14)]
    deleted = [make_deleted("contested.jpg", 2, tie)]

    result = partition_annotations_df(_df(rows), deleted)

    assert [d.image_name for d in result.deleted_images] == ["contested.jpg"]
    assert "contested.jpg" not in set(result.dataset["image_name"])
    contested_obsolete = result.obsolete[result.obsolete["image_name"] == "contested.jpg"]
    assert len(contested_obsolete) == 2


def test_a_row_without_a_task_id_loses_to_one_that_has_it() -> None:
    """A missing ``task_id`` sorts last instead of aborting the partition.

    ``completed_task_ids`` already drops such rows, so the row belongs to no
    task and cannot be the latest one for its image.
    """
    orphan = _row("a.jpg", 1, "2026-01-01T00:00:00")
    orphan["task_id"] = None
    rows = [orphan, _row("a.jpg", 2, "2026-01-02T00:00:00")]

    result = partition_annotations_df(_df(rows), [])

    assert result.dataset["task_id"].tolist() == [2]
    assert len(result.dataset) + len(result.obsolete) + len(result.in_progress) == 2


def test_result_frames_keep_the_input_columns_and_a_fresh_index() -> None:
    """Partition outputs carry no leftover index column and restart numbering."""
    rows = [
        _row("a.jpg", 1, "2026-01-01T00:00:00"),
        _row("a.jpg", 2, "2026-01-02T00:00:00"),
        _row("b.jpg", 3, "2026-01-03T00:00:00", status="in progress"),
    ]

    result = partition_annotations_df(_df(rows), [])

    for name, frame in (
        ("dataset", result.dataset),
        ("obsolete", result.obsolete),
        ("in_progress", result.in_progress),
    ):
        assert list(frame.columns) == _COLS, f"{name} gained or lost a column"
        assert list(frame.index) == list(range(len(frame))), f"{name} index not reset"


# ---------------------------------------------------------------------------
# Job stage/state aggregation
# ---------------------------------------------------------------------------


def _job_row(
    image: str,
    task_id: int,
    updated: str,
    stage: str,
    state: str,
) -> dict[str, object]:
    return csv_row(image, task_id=task_id, updated=updated, job_stage=stage, job_state=state)


@pytest.mark.parametrize(
    ("stage", "state"),
    [
        ("acceptance", "in progress"),
        ("validation", "completed"),
        ("annotation", "completed"),
        ("acceptance", "rejected"),
    ],
)
def test_only_acceptance_plus_completed_counts_as_finished(
    stage: str,
    state: str,
) -> None:
    """Either half of the pair alone leaves the task unfinished."""
    rows = [_job_row("a.jpg", 1, "2026-01-02T00:00:00", stage, state)]

    result = partition_annotations_df(_df(rows), [])

    assert len(result.dataset) == 0
    assert len(result.in_progress) == 1

"""Unit tests for partition_annotations_df (dataset / obsolete / in_progress)."""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from cveta2.domain.models import CSV_COLUMNS, DeletedImage
from cveta2.domain.partition import (
    PartitionResult,
    completed_task_ids,
    in_progress_table,
    partition_annotations_df,
)
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
# ``None`` is an unknown job position (legacy rows without stage/state), which
# holds its task back exactly like an unfinished one.
_Record = tuple[str, int, bool | None]
_RECORDS = st.tuples(
    st.sampled_from(["a.jpg", "b.jpg", "c.jpg"]),
    st.integers(1, 5),
    st.sampled_from([True, False, None]),
)


def _expected_partition(
    rows: list[_Record], deletions: list[_Record]
) -> tuple[dict[str, set[int]], list[tuple[str, int]], list[tuple[str, int]], list[tuple[str, int]]]:
    """Specify the partition: row positions per part, deleted and pending images.

    A task is complete when every row and deletion record of it is finished,
    and only complete tasks decide an image. Its completed result is the
    highest complete task id; a deletion wins a tie within its own task.

    * Result "deleted": the image is deleted and all its rows are obsolete,
      unless a newer unfinished task holds it as a live frame (a row with no
      deletion in the same task). Then it is reopened: the newest complete
      task holding it live goes to in_progress, the other complete rows
      to obsolete.
    * Result "annotated": that task goes to dataset, older complete tasks
      to obsolete.
    * Rows of unfinished tasks go to in_progress unless the image is deleted;
      unfinished deletions newer than the result are pending.
    * A reopened image keeps its completed deletion as a marker.
    """
    unfinished = {task for _, task, done in rows + deletions if not done}
    removed = {(image, task) for image, task, _ in deletions}
    parts: dict[str, set[int]] = {
        "dataset": set(),
        "obsolete": set(),
        "in_progress": set(),
    }
    deleted: list[tuple[str, int]] = []
    pending: set[tuple[str, int]] = set()
    reopened_by: list[tuple[str, int]] = []
    for image in {image for image, _, _ in rows + deletions}:
        mine = [(position, task) for position, (i, task, _) in enumerate(rows) if i == image]
        results = [(task, False) for _, task in mine if task not in unfinished]
        results += [(task, True) for i, task, _ in deletions if i == image and task not in unfinished]
        # Drawn task ids start at 1, so task 0 stands for "no completed result".
        result_task, removed_by_result = max(results, default=(0, False))
        live_unfinished = [task for _, task in mine if task in unfinished and (image, task) not in removed]
        reopened = removed_by_result and any(task > result_task for task in live_unfinished)
        is_deleted = removed_by_result and not reopened
        carried = max(
            (task for _, task in mine if task not in unfinished and (image, task) not in removed),
            default=None,
        )
        for position, task in mine:
            if is_deleted:
                part = "obsolete"
            elif task in unfinished:
                part = "in_progress"
            elif reopened:
                part = "in_progress" if task == carried else "obsolete"
            else:
                part = "dataset" if task == result_task else "obsolete"
            parts[part].add(position)
        if reopened:
            reopened_by.append((image, result_task))
        if is_deleted:
            deleted.append((image, result_task))
        else:
            pending |= {
                (image, task) for i, task, _ in deletions if i == image and task in unfinished and task > result_task
            }
    return parts, sorted(deleted), sorted(pending), sorted(reopened_by)


def _status(done: bool | None) -> str:  # noqa: FBT001 - maps a drawn flag
    return "completed" if done else "annotation"


def _drawn_row(record: _Record) -> dict[str, object]:
    image, task, done = record
    row = _row(image, task, f"2026-01-{31 - task:02d}T00:00:00", _status(done))
    if done is None:
        row.update(job_stage=None, job_state=None)
    return row


def _drawn_deletion(drawn: _Record) -> DeletedImage:
    image, task, done = drawn
    record = make_deleted(image, task, f"2026-01-{31 - task:02d}T00:00:00", _status(done))
    return record.model_copy(update={"job_stage": "", "job_state": ""}) if done is None else record


def _partition(rows: list[_Record], deletions: list[_Record]) -> PartitionResult:
    """Partition drawn records; task dates run against task ids on purpose."""
    frame = _df([_drawn_row(record) for record in rows]).assign(row=range(len(rows)))
    return partition_annotations_df(frame, [_drawn_deletion(record) for record in deletions])


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
# Case 1: deleted by completed task 3, reopened by unfinished task 5.
@example(rows=[("a.jpg", 1, True), ("a.jpg", 2, True), ("a.jpg", 5, False)], deletions=[("a.jpg", 3, True)])
# An unfinished task that also deletes the frame holds no live frame: still deleted.
@example(rows=[("a.jpg", 1, True), ("a.jpg", 5, False)], deletions=[("a.jpg", 3, True), ("a.jpg", 5, False)])
# Case 2: an unfinished deletion waits; the completed annotation stays.
@example(rows=[("a.jpg", 1, True), ("a.jpg", 5, False)], deletions=[("a.jpg", 5, False)])
# Case 1 where the deleting task kept shapes on the frame: the earlier annotation is carried.
@example(rows=[("a.jpg", 1, True), ("a.jpg", 3, True), ("a.jpg", 5, False)], deletions=[("a.jpg", 3, True)])
# A deleted-frame row of one unfinished task does not hide a newer live one listed after it.
@example(
    rows=[("a.jpg", 1, True), ("a.jpg", 4, False), ("a.jpg", 5, False)],
    deletions=[("a.jpg", 3, True), ("a.jpg", 4, False)],
)
# The newest unfinished task decides reopening, whatever the row order.
@example(rows=[("a.jpg", 1, True), ("a.jpg", 5, False), ("a.jpg", 2, False)], deletions=[("a.jpg", 3, True)])
def test_partition_matches_specification(rows: list[_Record], deletions: list[_Record]) -> None:
    """Every row lands in exactly the part the specification assigns.

    Task dates are deliberately reversed against task ids: only the id orders
    tasks, so a project-wide label edit that rewrites every date cannot
    scramble the partition.
    """
    result = _partition(rows, deletions)

    parts, deleted, pending, reopened = _expected_partition(rows, deletions)
    assert {
        "dataset": set(result.dataset["row"]),
        "obsolete": set(result.obsolete["row"]),
        "in_progress": set(result.in_progress["row"]),
    } == parts
    assert len(result.dataset) + len(result.obsolete) + len(result.in_progress) == len(rows)
    assert [(d.image_name, d.task_id) for d in result.deleted_images] == deleted
    assert [(d.image_name, d.task_id) for d in result.pending_deletions] == pending
    assert [(d.image_name, d.task_id, d.task_completed) for d in result.reopened_deletions] == [
        (image, task, True) for image, task in reopened
    ]


def _tasks_by_part(result: PartitionResult) -> dict[str, list[int]]:
    return {
        "dataset": sorted(result.dataset["task_id"]),
        "obsolete": sorted(result.obsolete["task_id"]),
        "in_progress": sorted(result.in_progress["task_id"]),
        "deleted": [d.task_id for d in result.deleted_images],
        "pending": [d.task_id for d in result.pending_deletions],
        "reopened": [d.task_id for d in result.reopened_deletions],
    }


def test_completed_deletion_reopened_by_a_newer_unfinished_task() -> None:
    """Case 1: the old boxes wait in in_progress with the re-annotation.

    Completed task 3 annotated the image, completed task 5 deleted it and
    unfinished task 9 holds it again. Nothing reaches dataset.csv or
    deleted.csv until task 9 completes.
    """
    result = _partition(
        rows=[("a.jpg", 3, True), ("a.jpg", 9, False)],
        deletions=[("a.jpg", 5, True)],
    )

    assert _tasks_by_part(result) == {
        "dataset": [],
        "obsolete": [],
        "in_progress": [3, 9],
        "deleted": [],
        "pending": [],
        "reopened": [5],
    }


def test_unfinished_deletion_waits_for_its_task() -> None:
    """Case 2: the completed boxes stay in dataset; the deletion is pending."""
    result = _partition(
        rows=[("a.jpg", 3, True), ("a.jpg", 9, False)],
        deletions=[("a.jpg", 9, False)],
    )

    assert _tasks_by_part(result) == {
        "dataset": [3],
        "obsolete": [],
        "in_progress": [9],
        "deleted": [],
        "pending": [9],
        "reopened": [],
    }


@pytest.mark.parametrize(
    ("rows", "deletions", "expected"),
    [
        pytest.param(
            [("a.jpg", 1, False)],
            [("a.jpg", 2, True)],
            {"dataset": [], "obsolete": [1], "in_progress": [], "deleted": [2], "pending": [], "reopened": []},
            id="unfinished-task-older-than-the-completed-deletion",
        ),
        pytest.param(
            [],
            [("a.jpg", 1, True), ("a.jpg", 2, False)],
            {"dataset": [], "obsolete": [], "in_progress": [], "deleted": [1], "pending": [], "reopened": []},
            id="unfinished-deletion-after-a-completed-deletion",
        ),
        pytest.param(
            [("a.jpg", 2, False)],
            [("a.jpg", 1, True), ("a.jpg", 2, False)],
            {"dataset": [], "obsolete": [2], "in_progress": [], "deleted": [1], "pending": [], "reopened": []},
            id="unfinished-task-that-annotates-and-deletes-does-not-reopen",
        ),
        pytest.param(
            [("a.jpg", 2, False)],
            [("a.jpg", 1, True)],
            {"dataset": [], "obsolete": [], "in_progress": [2], "deleted": [], "pending": [], "reopened": [1]},
            id="reopened-without-earlier-completed-boxes",
        ),
    ],
)
def test_accepted_edges_of_completed_deletions(
    rows: list[_Record], deletions: list[_Record], expected: dict[str, list[int]]
) -> None:
    """Edges the decision did not spell out; the owner accepted these outcomes."""
    assert _tasks_by_part(_partition(rows, deletions)) == expected


def test_unfinished_reannotation_keeps_the_completed_result() -> None:
    """Without any deletion, a newer unfinished task leaves dataset.csv alone."""
    result = _partition(rows=[("a.jpg", 3, True), ("a.jpg", 9, False)], deletions=[])

    assert _tasks_by_part(result) == {
        "dataset": [3],
        "obsolete": [],
        "in_progress": [9],
        "deleted": [],
        "pending": [],
        "reopened": [],
    }


def test_in_progress_table_appends_pending_deletions_without_reformatting_rows() -> None:
    """Pending deletions follow the unfinished rows as ``deleted`` rows.

    The sparse deletion row must not turn the annotation rows' integer
    columns into floats in the written table.
    """
    rows = [
        csv_row("a.jpg", task_id=3, updated="2026-01-01T00:00:00", status="completed"),
        csv_row("a.jpg", task_id=9, updated="2026-01-02T00:00:00", status="annotation"),
    ]
    frame = make_df(rows, columns=list(CSV_COLUMNS))
    deleted = make_deleted("a.jpg", 9, "2026-01-02T00:00:00", "annotation")

    result = partition_annotations_df(frame, [deleted])
    table = in_progress_table(result)

    assert table["instance_shape"].tolist() == ["box", "deleted"]
    assert table["task_id"].tolist() == [9, 9]
    unfinished_text = result.in_progress.to_csv(index=False).splitlines()
    assert table.to_csv(index=False).splitlines()[: len(unfinished_text)] == unfinished_text


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

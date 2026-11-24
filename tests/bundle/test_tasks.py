"""Task manifests rely on original fetch provenance, never validation filtering."""

import pandas as pd
import pytest

from cveta2.domain.bundle.models import FetchTables, TaskManifest, UploadError
from cveta2.domain.bundle.tasks import derive_tasks, trace_tasks


def frame(*rows: tuple[object, str, object]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["task_id", "image_name", "task_completed"])


def tables(
    dataset: pd.DataFrame,
    *,
    obsolete: pd.DataFrame | None = None,
    in_progress: pd.DataFrame | None = None,
    deleted: pd.DataFrame | None = None,
) -> FetchTables:
    return FetchTables(
        dataset,
        pd.DataFrame() if obsolete is None else obsolete,
        pd.DataFrame() if in_progress is None else in_progress,
        pd.DataFrame() if deleted is None else deleted,
    )


def test_full_supersession_and_deletion_use_original_not_clean() -> None:
    source = tables(
        frame((3, "a", True), (4, "b", "True")),
        obsolete=frame((1, "a", True), (1, "b", True), (2, "deleted", True)),
        deleted=frame((5, "deleted", False)),
    )
    manifest = derive_tasks(source, frame((4, "b", True)))
    assert manifest.included == [4]
    assert manifest.obsolete == [1, 2]


def test_partial_unfinished_and_validation_only_rejections_are_not_obsolete() -> None:
    source = tables(
        frame((2, "a", True), (1, "b", True), (4, "c", True)),
        obsolete=frame((1, "a", True), (3, "c", True)),
        in_progress=frame((3, "d", False), (5, "b", False)),
    )
    manifest = derive_tasks(source, frame((1, "b", True)))
    assert manifest.included == [1]
    assert manifest.obsolete == []


def test_legacy_completion_fallback_and_conflicting_evidence() -> None:
    legacy = pd.DataFrame(
        {
            "task_id": [1, 2],
            "image_name": ["a", "a"],
            "job_stage": ["acceptance"] * 2,
            "job_state": ["completed"] * 2,
        }
    )
    assert derive_tasks(tables(legacy), legacy.iloc[[1]]).obsolete == [1]
    unfinished = frame((1, "z", "false"))
    assert derive_tasks(tables(legacy, deleted=unfinished), legacy.iloc[[1]]).obsolete == []


def test_completion_unknown_disqualifies_task_and_cannot_supersede() -> None:
    source = tables(frame((2, "a", "garbage")), obsolete=frame((1, "a", True)))
    assert derive_tasks(source, pd.DataFrame()).obsolete == []


@pytest.mark.parametrize("invalid", [True, 1.5, "-1", None, "NaN"])
def test_strict_task_ids_reject_ambiguous_provenance(invalid: object) -> None:
    with pytest.raises(UploadError):
        derive_tasks(tables(frame((invalid, "a", True))), pd.DataFrame())


def test_included_are_sorted_unique_and_must_have_source_provenance() -> None:
    source = tables(frame(("10", "a", "true"), ("2", "b", "true")))
    assert derive_tasks(source, frame(("10", "a", True), ("2", "b", True), ("10", "a", True))).included == [
        2,
        10,
    ]
    with pytest.raises(UploadError):
        derive_tasks(source, frame((99, "a", True)))


def test_integral_csv_numeric_ids_are_accepted_without_truncation() -> None:
    source = tables(frame(("12.0", "a", True), (0.0, "b", True)))
    assert derive_tasks(source, source.dataset).included == [0, 12]


def test_in_progress_rows_without_explicit_completion_fail_closed() -> None:
    """A legacy in-progress row may belong to a task with an unseen unfinished job."""
    legacy = pd.DataFrame(
        {
            "task_id": [1],
            "image_name": ["a"],
            "instance_shape": ["box"],
            "job_stage": ["acceptance"],
            "job_state": ["completed"],
        },
    )
    source = tables(frame((2, "a", True)), obsolete=frame((1, "a", True)), in_progress=legacy)
    assert derive_tasks(source, source.dataset).obsolete == []


def test_completed_boxes_waiting_in_progress_still_supersede() -> None:
    """Task 3's boxes of a reopened image wait in in_progress.csv; task 3 stays completed.

    Task 3 also replaced task 1's annotation of another image, so task 1
    remains fully superseded.
    """
    source = tables(
        frame((3, "y", True)),
        obsolete=frame((1, "y", True)),
        in_progress=frame((3, "x", True), (9, "x", False)),
    )
    assert derive_tasks(source, source.dataset) == TaskManifest(included=[3], obsolete=[1])


def test_missing_completion_and_null_legacy_fallback() -> None:
    source = tables(frame((2, "a", True)), obsolete=frame((1, "a", None)))
    assert derive_tasks(source, source.dataset).obsolete == []
    source.obsolete["job_stage"] = "acceptance"
    source.obsolete["job_state"] = "completed"
    assert derive_tasks(source, source.dataset).obsolete == [1]


def test_every_partition_contributes_unfinished_task_evidence() -> None:
    source = tables(
        frame((3, "a", True)),
        obsolete=frame((1, "a", True), (1, "b", False)),
        deleted=frame((4, "b", True)),
    )
    assert derive_tasks(source, source.dataset).obsolete == []


def test_higher_unfinished_annotation_does_not_supersede_completed_task() -> None:
    source = tables(frame((1, "a", True)), in_progress=frame((2, "a", False)))
    assert derive_tasks(source, pd.DataFrame()).obsolete == []


def test_clean_rows_cannot_resurrect_obsolete_annotations() -> None:
    old = frame((1, "a", True))
    source = tables(frame((2, "a", True)), obsolete=old)
    with pytest.raises(UploadError, match=r"dataset\.csv"):
        derive_tasks(source, old)


def test_deletion_markers_in_progress_do_not_change_the_manifest() -> None:
    """Pending and reopened deletion rows of in_progress.csv are markers, not task evidence."""
    carried = frame((3, "x", True), (9, "x", False)).assign(instance_shape="box")
    markers = frame((5, "x", True), (9, "z", False)).assign(instance_shape="deleted")
    # Task 3 appears only through its carried boxes; counting task 5's marker
    # as a completed annotation would supersede them and list task 3 obsolete.
    without = tables(frame((4, "y", True)), in_progress=carried)
    with_markers = tables(frame((4, "y", True)), in_progress=pd.concat([carried, markers], ignore_index=True))

    expected = TaskManifest(included=[4], obsolete=[])
    assert derive_tasks(without, without.dataset) == expected
    assert derive_tasks(with_markers, with_markers.dataset) == expected


def test_a_legacy_pending_deletion_keeps_its_task_open() -> None:
    """A pending deletion without task_completed is the only evidence that task 7 is unfinished."""

    def rows(*records: tuple[int, str, str, str, str]) -> pd.DataFrame:
        columns = ["task_id", "image_name", "instance_shape", "job_stage", "job_state"]
        return pd.DataFrame(records, columns=columns).assign(task_completed="")

    source = tables(
        rows((2, "y.jpg", "box", "acceptance", "completed")),
        obsolete=rows((7, "x.jpg", "box", "acceptance", "completed")),
        in_progress=rows((7, "y.jpg", "deleted", "annotation", "new")),
        deleted=rows((8, "x.jpg", "deleted", "acceptance", "completed")),
    )

    assert derive_tasks(source, source.dataset).obsolete == []


@pytest.mark.parametrize(
    ("flag", "is_marker"),
    [(True, True), ("True", True), ("true", True), (False, False), ("", False), ("1", False), (1, False)],
)
def test_only_an_explicitly_true_deleted_row_is_a_reopen_marker(flag: object, *, is_marker: bool) -> None:
    """A marker is skipped; any other flag keeps the row as evidence that task 5 is not finished.

    Task 6 superseded task 5's only image, so task 5 is listed obsolete exactly
    when nothing says it is unfinished.
    """
    deleted_row = pd.DataFrame([{"task_id": 5, "image_name": "x", "instance_shape": "deleted", "task_completed": flag}])
    source = tables(frame((6, "z", True)), obsolete=frame((5, "z", True)), in_progress=deleted_row)

    assert derive_tasks(source, source.dataset).obsolete == ([5] if is_marker else [])


def test_trace_tasks_counts_untraceable_rows() -> None:
    source = tables(frame((3, "a", True)), obsolete=frame((1, "a", True)))
    traced = trace_tasks(source, frame((3, "a", True), (99, "a", True), ("", "a", True)))
    assert traced.untraced_rows == 2
    assert traced.manifest == TaskManifest(included=[3], obsolete=[1])


@pytest.mark.parametrize(
    "clean",
    [pd.DataFrame(), frame(), pd.DataFrame({"image_name": ["a"]}), frame((3, "", True), (3.5, "a", True))],
)
def test_trace_tasks_never_raises_on_the_clean_frame(clean: pd.DataFrame) -> None:
    traced = trace_tasks(tables(frame((3, "a", True))), clean)
    assert traced.untraced_rows == len(clean)
    assert traced.manifest.included == []

"""Task manifests rely on original fetch provenance, never validation filtering."""

import pandas as pd
import pytest

from cveta2.domain.bundle.models import FetchTables, UploadError
from cveta2.domain.bundle.tasks import derive_tasks


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
    assert (
        derive_tasks(tables(legacy, deleted=unfinished), legacy.iloc[[1]]).obsolete
        == []
    )


def test_completion_unknown_disqualifies_task_and_cannot_supersede() -> None:
    source = tables(frame((2, "a", "garbage")), obsolete=frame((1, "a", True)))
    assert derive_tasks(source, pd.DataFrame()).obsolete == []


@pytest.mark.parametrize("invalid", [True, 1.5, "-1", None, "NaN"])
def test_strict_task_ids_reject_ambiguous_provenance(invalid: object) -> None:
    with pytest.raises(UploadError):
        derive_tasks(tables(frame((invalid, "a", True))), pd.DataFrame())


def test_included_are_sorted_unique_and_must_have_source_provenance() -> None:
    source = tables(frame(("10", "a", "true"), ("2", "b", "true")))
    assert derive_tasks(
        source, frame(("10", "a", True), ("2", "b", True), ("10", "a", True))
    ).included == [
        2,
        10,
    ]
    with pytest.raises(UploadError):
        derive_tasks(source, frame((99, "a", True)))


def test_integral_csv_numeric_ids_are_accepted_without_truncation() -> None:
    source = tables(frame(("12.0", "a", True), (0.0, "b", True)))
    assert derive_tasks(source, source.dataset).included == [0, 12]


def test_in_progress_partition_conflicts_fail_closed() -> None:
    source = tables(
        frame((2, "a", True)),
        obsolete=frame((1, "a", True)),
        in_progress=frame((1, "b", True)),
    )
    assert derive_tasks(source, source.dataset).obsolete == []


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

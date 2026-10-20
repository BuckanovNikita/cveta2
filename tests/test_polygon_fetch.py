"""Polygon regressions through the public fetch APIs and their CSV output."""

from pathlib import Path

import pytest

import cveta2
from cveta2.adapters.config.settings import CvatConfig
from cveta2.adapters.files.dataset import read_dataset_csv
from cveta2.application.ports.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawIssue,
)
from cveta2.composition.client import CvatClient
from cveta2.domain.models import CSV_COLUMNS, LabelInfo, ProjectInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.helpers import make_raw_shape, make_task


def _polygon_connection(*, deleted: bool, malformed: bool) -> cveta2.Connection:
    task = make_task(41, name="polygon-task")
    shape = make_raw_shape(
        id=73,
        type="polygon",
        points=[12.0, 30.5, 90.75, 10.25, 40.5, 80.0][:-1]
        if malformed
        else [12.0, 30.5, 90.75, 10.25, 40.5, 80.0],
        rotation=37.0,
    )
    api = FakeCvatApi(
        LoadedFixtures(
            project=ProjectInfo(id=1, name="polygon-project"),
            tasks=[task],
            labels=[LabelInfo(id=1, name="car")],
            task_data={
                task.id: (
                    RawDataMeta(
                        [RawFrame("polygon.jpg", 100, 100)],
                        deleted_frames=[0] if deleted else [],
                    ),
                    RawAnnotations([shape]),
                )
            },
            issues={
                task.id: [RawIssue(9, 0, resolved=False, comments=["Check outline"])]
            },
        )
    )
    return cveta2.Connection(client=CvatClient(CvatConfig(), api=api))


@pytest.mark.parametrize("selected", [False, True], ids=["fetch", "fetch-task"])
@pytest.mark.parametrize("deleted", [False, True], ids=["active", "deleted"])
def test_polygon_box_survives_fetch_with_existing_deletion_semantics(
    tmp_path: Path, *, selected: bool, deleted: bool
) -> None:
    """Polygon-only frames are annotated; project partitioning still honors deletion."""
    connection = _polygon_connection(deleted=deleted, malformed=False)
    if selected:
        cveta2.fetch_task(
            [41],
            tmp_path,
            project=1,
            connection=connection,
            download_images=False,
            cache="off",
        )
    else:
        cveta2.fetch(
            1,
            tmp_path,
            connection=connection,
            download_images=False,
            cache="off",
        )

    dataset = read_dataset_csv(tmp_path / "dataset.csv", set(CSV_COLUMNS))
    assert list(dataset.columns) == list(CSV_COLUMNS)
    if deleted and not selected:
        assert dataset.empty
        boxes = read_dataset_csv(tmp_path / "obsolete.csv", set(CSV_COLUMNS))
    else:
        boxes = dataset
    assert boxes["instance_shape"].tolist() == ["box"]
    row = boxes.iloc[0]
    assert tuple(row[["bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"]]) == (
        12.0,
        10.25,
        90.75,
        80.0,
    )
    assert row["rotation"] == 0.0
    assert row["instance_label"] == "car"
    assert row["annotation_id"] == 73
    assert row["task_id"] == 41
    assert row["frame_id"] == 0
    assert row["image_name"] == "polygon.jpg"
    assert row["issue_text"] == "Check outline"
    assert row["issue_state"] == "open"

    deletions = read_dataset_csv(tmp_path / "deleted.csv", set(CSV_COLUMNS))
    assert deletions["instance_shape"].tolist() == (["deleted"] if deleted else [])
    if deleted:
        assert deletions["image_name"].tolist() == ["polygon.jpg"]


@pytest.mark.parametrize("selected", [False, True], ids=["fetch", "fetch-task"])
def test_rejected_polygon_retains_unannotated_frame(
    tmp_path: Path, *, selected: bool
) -> None:
    """Rejecting malformed geometry preserves the frame and its issues."""
    connection = _polygon_connection(deleted=False, malformed=True)
    if selected:
        cveta2.fetch_task(
            [41],
            tmp_path,
            project=1,
            connection=connection,
            download_images=False,
            cache="off",
        )
    else:
        cveta2.fetch(
            1,
            tmp_path,
            connection=connection,
            download_images=False,
            cache="off",
        )
    dataset = read_dataset_csv(tmp_path / "dataset.csv", set(CSV_COLUMNS))
    assert dataset["instance_shape"].tolist() == ["none"]
    assert dataset["issue_text"].tolist() == ["Check outline"]

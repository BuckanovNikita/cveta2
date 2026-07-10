"""Unit tests for the ``cveta2 task`` write operations (CLI + client)."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pandas as pd
import pytest

from cveta2._client.dtos import RawAnnotations, RawDataMeta, RawFrame, RawJob
from cveta2._client.ports import CvatApiPort
from cveta2.client import CvatClient
from cveta2.commands.task_ops import (
    STATE_CLI_TO_CVAT,
    run_task_mark_deleted,
    run_task_status,
)
from cveta2.exceptions import Cveta2Error
from cveta2.models import LabelInfo, TaskInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import (
    client_with_api,
    csv_row,
    make_raw_shape,
    mock_client_ctx,
    parse_cli_args,
    patch_cli_client,
)

if TYPE_CHECKING:
    from tests.fixtures.fake_cvat_project import LoadedFixtures

# ---------------------------------------------------------------------------
# Command validation and state mapping
# ---------------------------------------------------------------------------


def _mock_client_with_task(task: TaskInfo) -> MagicMock:
    client = mock_client_ctx()
    client.list_project_tasks.return_value = [task]
    client.resolve_task_selectors = CvatClient.resolve_task_selectors
    return client


class TestRunTaskCommands:
    def test_mark_deleted_requires_frame_or_image(self) -> None:
        args = argparse.Namespace(project="p", task="1", frame=None, image=None)
        with pytest.raises(Cveta2Error):
            run_task_mark_deleted(args)

    def test_status_requires_stage_or_state(self) -> None:
        args = argparse.Namespace(project="p", task="1", stage=None, state=None)
        with pytest.raises(Cveta2Error):
            run_task_status(args)

    def test_state_mapping_covers_all_cli_values(self) -> None:
        assert STATE_CLI_TO_CVAT["in-progress"] == "in progress"
        assert STATE_CLI_TO_CVAT["new"] == "new"
        assert STATE_CLI_TO_CVAT["completed"] == "completed"
        assert STATE_CLI_TO_CVAT["rejected"] == "rejected"

    @pytest.mark.usefixtures("test_config")
    def test_status_passes_mapped_state_to_client(self) -> None:
        task = TaskInfo(
            id=42, name="task-a", status="annotation", subset="", updated_date=""
        )
        client = _mock_client_with_task(task)
        args = parse_cli_args(
            "task", "status", "-p", "1", "-t", "task-a", "--state", "in-progress"
        )
        with patch_cli_client(client):
            run_task_status(args)
        client.set_task_jobs_status.assert_called_once_with(
            42, stage=None, state="in progress"
        )


# ---------------------------------------------------------------------------
# Client write methods at the API-port boundary
# ---------------------------------------------------------------------------


def _client_with_api(api: MagicMock) -> CvatClient:
    return client_with_api(api)


class TestFakeWriteChain:
    """The recording FakeCvatApi supports the full CVAT upload half."""

    def test_upload_chain_runs_against_fake(self, normal_fake: LoadedFixtures) -> None:
        fake_api = FakeCvatApi(normal_fake)
        client = client_with_api(fake_api)
        label = normal_fake.labels[0].name

        task_id = client.create_upload_task(
            project_id=normal_fake.project.id,
            name="upload-1",
            image_names=["2026-01/a.jpg", "2026-01/b.jpg"],
            cloud_storage_id=1,
        )
        session = client.open_task_session(task_id)
        df = pd.DataFrame([csv_row("a.jpg", label=label)])
        num_shapes = client.upload_task_annotations(task_id, df, session=session)
        marked = client.mark_frames_deleted(task_id, {"b.jpg"}, session=session)
        num_jobs = client.complete_task(task_id)

        assert num_shapes == 1
        assert marked == 1
        assert num_jobs == 1
        assert [s.frame for s in fake_api.writes.shapes[task_id]] == [0]
        assert fake_api.writes.deleted_frames[task_id] == [1]
        assert fake_api.writes.job_updates == [(task_id, "acceptance", "completed")]
        assert fake_api.get_task_data_meta(task_id).deleted_frames == [1]


class TestDropLabelAnnotations:
    def test_unknown_label_raises_value_error_with_available(self) -> None:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_labels.return_value = [
            LabelInfo(id=1, name="person"),
            LabelInfo(id=2, name="car"),
        ]
        client = _client_with_api(api)

        with pytest.raises(ValueError, match="person") as exc_info:
            client.count_task_label_shapes(5, "ghost")
        assert "car" in str(exc_info.value)
        assert "'ghost'" in str(exc_info.value)

    def test_drop_deletes_only_matching_shapes(self) -> None:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_labels.return_value = [
            LabelInfo(id=1, name="person"),
            LabelInfo(id=2, name="car"),
        ]
        matching = make_raw_shape(id=10, label_id=1, points=[1.0, 2.0, 3.0, 4.0])
        other = make_raw_shape(id=11, frame=1, label_id=2, points=[5.0, 6.0, 7.0, 8.0])
        api.get_task_annotations.return_value = RawAnnotations(shapes=[matching, other])
        client = _client_with_api(api)

        deleted = client.drop_label_annotations(5, "person")

        assert deleted == 1
        api.delete_shapes.assert_called_once_with(5, [matching])

    def test_drop_with_no_matching_shapes_returns_zero(self) -> None:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_labels.return_value = [LabelInfo(id=1, name="person")]
        api.get_task_annotations.return_value = RawAnnotations(shapes=[])
        client = _client_with_api(api)

        assert client.drop_label_annotations(5, "person") == 0
        api.delete_shapes.assert_not_called()


class TestMarkFramesDeletedByIds:
    def test_skips_unknown_frame_ids_with_warning(
        self, capture_logs: list[str]
    ) -> None:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_data_meta.return_value = RawDataMeta(
            frames=[
                RawFrame(name="a.jpg", width=10, height=10),
                RawFrame(name="b.jpg", width=10, height=10),
                RawFrame(name="c.jpg", width=10, height=10),
            ],
            deleted_frames=[0],
        )
        client = _client_with_api(api)

        marked = client.mark_frames_deleted_by_ids(7, [1, 5, -1])

        assert marked == 1
        api.set_deleted_frames.assert_called_once_with(7, [0, 1])
        assert any("5" in msg and "-1" in msg for msg in capture_logs)

    def test_all_unknown_ids_makes_no_api_call(self) -> None:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_data_meta.return_value = RawDataMeta(
            frames=[RawFrame(name="a.jpg", width=10, height=10)],
            deleted_frames=[],
        )
        client = _client_with_api(api)

        assert client.mark_frames_deleted_by_ids(7, [3, 4]) == 0
        api.set_deleted_frames.assert_not_called()


class TestSetTaskJobsStatus:
    def test_requires_stage_or_state(self) -> None:
        client = _client_with_api(MagicMock(spec=CvatApiPort))
        with pytest.raises(ValueError, match="stage"):
            client.set_task_jobs_status(1)

    def test_patches_only_provided_fields(self) -> None:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_jobs.return_value = [RawJob(id=100, start_frame=0, stop_frame=9)]
        client = _client_with_api(api)

        num_jobs = client.set_task_jobs_status(1, state="in progress")

        assert num_jobs == 1
        api.update_job.assert_called_once_with(100, stage=None, state="in progress")

    def test_complete_task_sets_acceptance_completed(self) -> None:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_jobs.return_value = [
            RawJob(id=100, start_frame=0, stop_frame=9),
            RawJob(id=101, start_frame=10, stop_frame=19),
        ]
        client = _client_with_api(api)

        num_jobs = client.complete_task(1)

        assert num_jobs == 2
        assert api.update_job.call_count == 2
        api.update_job.assert_called_with(101, stage="acceptance", state="completed")

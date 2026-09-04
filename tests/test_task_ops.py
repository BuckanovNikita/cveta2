"""Unit tests for the ``cveta2 task`` write operations (CLI + client)."""

from __future__ import annotations

import argparse
import re
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pandas as pd
import pytest

from cveta2._client.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawJob,
    UploadTaskSpec,
)
from cveta2._client.ports import CvatApiPort
from cveta2.client import CvatClient
from cveta2.commands.task_ops import (
    STATE_CLI_TO_CVAT,
    run_task_mark_deleted,
    run_task_status,
)
from cveta2.exceptions import CvatApiError, Cveta2Error
from cveta2.models import LabelInfo, TaskInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import (
    CFG,
    client_with_api,
    csv_row,
    make_raw_shape,
    mock_client_ctx,
    parse_cli_args,
    patch_cli_client,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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


def _api_with_frames(*names: str, deleted: list[int] | None = None) -> MagicMock:
    """Build a mocked port whose task exposes *names* as consecutive frames."""
    api = MagicMock(spec=CvatApiPort)
    api.get_task_data_meta.return_value = RawDataMeta(
        frames=[RawFrame(name=name, width=10, height=10) for name in names],
        deleted_frames=deleted if deleted is not None else [],
    )
    return api


# Every remote method funnels through ``_require_api(<own name>)``, whose only
# observable effect outside a context manager is the raised message.  Without
# this table the method name in that message is dead weight no test reads.
_CONTEXT_REQUIRED_CALLS: list[tuple[str, Callable[[CvatClient], object]]] = [
    ("mark_frames_deleted", lambda c: c.mark_frames_deleted(1, {"a.jpg"})),
    ("mark_frames_deleted_by_ids", lambda c: c.mark_frames_deleted_by_ids(1, [0])),
    ("count_task_label_shapes", lambda c: c.count_task_label_shapes(1, "cat")),
    ("drop_label_annotations", lambda c: c.drop_label_annotations(1, "cat")),
    ("delete_task", lambda c: c.delete_task(1)),
    ("count_task_shapes", lambda c: c.count_task_shapes(1)),
    ("get_task_size", lambda c: c.get_task_size(1)),
    ("set_task_jobs_status", lambda c: c.set_task_jobs_status(1, state="completed")),
    ("update_project_labels", lambda c: c.update_project_labels(1, add=["cat"])),
    ("create_upload_task", lambda c: c.create_upload_task(1, "t", ["a.jpg"], 2)),
    ("upload_task_annotations", lambda c: c.upload_task_annotations(1, pd.DataFrame())),
    ("create_task_issues", lambda c: c.create_task_issues(1, pd.DataFrame())),
]


@pytest.mark.parametrize(
    ("method_name", "call"),
    _CONTEXT_REQUIRED_CALLS,
    ids=[name for name, _call in _CONTEXT_REQUIRED_CALLS],
)
def test_write_method_outside_context_names_itself(
    method_name: str, call: Callable[[CvatClient], object]
) -> None:
    """The context-manager error must name the method the caller invoked.

    Only ``test_update_labels_requires_context_manager`` covered this, and it
    matched on ``"context manager"`` alone — so every ``_require_api("…")``
    argument in both mixins could be replaced by ``None``, uppercased or
    padded without a single test noticing.  ``delete_task`` had no unit test
    at all and reported as uncovered.
    """
    client = CvatClient(CFG)
    expected = re.escape(f"{method_name}() requires a context manager")
    with pytest.raises(RuntimeError, match=expected):
        call(client)


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
    def test_unknown_label_raises_domain_error_with_available(self) -> None:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_labels.return_value = [
            LabelInfo(id=1, name="person"),
            LabelInfo(id=2, name="car"),
        ]
        client = _client_with_api(api)

        with pytest.raises(Cveta2Error, match="person") as exc_info:
            client.count_task_label_shapes(5, "ghost")
        # The joined, sorted list — not just its members — is the contract:
        # asserting membership alone left the ", " separator unpinned.
        assert "car, person" in str(exc_info.value)
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
        # A mocked port answers any task id identically, so without these the
        # task id could be dropped on the way into _find_label_shapes.
        api.get_task_labels.assert_called_once_with(5)
        api.get_task_annotations.assert_called_once_with(5)

    def test_drop_with_no_matching_shapes_returns_zero(self) -> None:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_labels.return_value = [LabelInfo(id=1, name="person")]
        api.get_task_annotations.return_value = RawAnnotations(shapes=[])
        client = _client_with_api(api)

        assert client.drop_label_annotations(5, "person") == 0
        api.delete_shapes.assert_not_called()


class TestMarkFramesDeleted:
    def test_opens_a_session_for_the_requested_task(self) -> None:
        """Both existing callers pass ``session=``, so the fallback was dead.

        With no test exercising it, ``session or self.open_task_session(...)``
        could become ``session and …`` and the session could be opened for a
        different task without anything failing.
        """
        api = _api_with_frames("a.jpg", "b.jpg")
        client = _client_with_api(api)

        assert client.mark_frames_deleted(7, {"b.jpg"}) == 1
        api.get_task_data_meta.assert_called_once_with(7)
        api.set_deleted_frames.assert_called_once_with(7, [1])


class TestMarkFramesDeletedByIds:
    def test_already_deleted_frame_is_not_patched_or_counted(self) -> None:
        api = _api_with_frames("a.jpg", "b.jpg", deleted=[1])
        client = _client_with_api(api)

        assert client.mark_frames_deleted_by_ids(7, [1]) == 0
        api.set_deleted_frames.assert_not_called()

    def test_skips_unknown_frame_ids_with_warning(
        self, capture_logs: list[str]
    ) -> None:
        api = _api_with_frames("a.jpg", "b.jpg", "c.jpg", deleted=[0])
        client = _client_with_api(api)

        marked = client.mark_frames_deleted_by_ids(7, [1, 5, -1])

        assert marked == 1
        api.get_task_data_meta.assert_called_once_with(7)
        api.set_deleted_frames.assert_called_once_with(7, [0, 1])
        assert any("5" in msg and "-1" in msg for msg in capture_logs)

    def test_all_unknown_ids_makes_no_api_call(self) -> None:
        api = _api_with_frames("a.jpg")
        client = _client_with_api(api)

        assert client.mark_frames_deleted_by_ids(7, [3, 4]) == 0
        api.set_deleted_frames.assert_not_called()

    def test_frame_zero_is_a_valid_id(self, capture_logs: list[str]) -> None:
        """0 is the first frame index, not a sentinel.

        The old cases used ``[1, 5, -1]`` and ``[3, 4]``, so neither lower
        bound was ever exercised at its boundary: ``0 <= fid`` could tighten
        to ``1 <= fid`` (or ``0 < fid``) and frame 0 would silently stop
        being deletable.
        """
        api = _api_with_frames("a.jpg", "b.jpg", "c.jpg")
        client = _client_with_api(api)

        assert client.mark_frames_deleted_by_ids(7, [0]) == 1
        api.set_deleted_frames.assert_called_once_with(7, [0])
        assert not any("не найдены" in msg for msg in capture_logs)

    def test_frame_count_itself_is_out_of_range(self, capture_logs: list[str]) -> None:
        """``num_frames`` is one past the last index.

        No previous case requested exactly ``num_frames``, so ``fid <
        num_frames`` could relax to ``<=`` and CVAT would be asked to delete
        a frame that does not exist.
        """
        api = _api_with_frames("a.jpg", "b.jpg", "c.jpg")
        client = _client_with_api(api)

        assert client.mark_frames_deleted_by_ids(7, [3]) == 0
        api.set_deleted_frames.assert_not_called()
        assert any("[3]" in msg for msg in capture_logs)

    def test_warning_lists_only_the_rejected_ids(self, capture_logs: list[str]) -> None:
        """The warning must name the skipped ids, not every requested one."""
        api = _api_with_frames("a.jpg", "b.jpg", "c.jpg")
        client = _client_with_api(api)

        assert client.mark_frames_deleted_by_ids(7, [0, 3]) == 1
        assert [msg for msg in capture_logs if "[3]" in msg]
        assert not any("[0, 3]" in msg for msg in capture_logs)


class TestDeleteTask:
    def test_forwards_the_task_id_to_the_port(self) -> None:
        """``delete_task`` is destructive and had only an integration test.

        mutmut reported it as uncovered, so nothing pinned *which* task the
        call destroys.
        """
        api = MagicMock(spec=CvatApiPort)
        client = _client_with_api(api)

        client.delete_task(9)

        api.delete_task.assert_called_once_with(9)


class TestCreateUploadTask:
    def test_every_argument_reaches_the_task_spec(self) -> None:
        """Only the fake-backed chain exercised this, and it never read the spec.

        Any field of ``UploadTaskSpec`` could therefore be dropped or blanked
        and the task would still be "created".
        """
        api = MagicMock(spec=CvatApiPort)
        api.create_task.return_value = 55
        client = _client_with_api(api)

        task_id = client.create_upload_task(
            project_id=3,
            name="up",
            image_names=["2026-01/a.jpg"],
            cloud_storage_id=9,
            segment_size=25,
            image_quality=70,
        )

        expected_spec = UploadTaskSpec(
            project_id=3,
            name="up",
            server_files=["2026-01/a.jpg"],
            cloud_storage_id=9,
            segment_size=25,
            image_quality=70,
        )
        assert task_id == 55
        api.create_task.assert_called_once_with(expected_spec)
        api.attach_task_data.assert_called_once_with(55, expected_spec)

    def test_segment_size_and_quality_default_to_one_hundred(self) -> None:
        """The two defaults are the client's own, not the DTO's, to callers."""
        api = MagicMock(spec=CvatApiPort)
        client = _client_with_api(api)

        client.create_upload_task(3, "up", ["a.jpg"], 9)

        spec = api.create_task.call_args.args[0]
        assert (spec.segment_size, spec.image_quality) == (100, 100)


class TestUploadTaskAnnotations:
    def test_opens_a_session_for_the_requested_task(self) -> None:
        """Uploading without a session opens one for that same task.

        Every existing caller supplied ``session=``, leaving the fallback
        path — and the task id it is opened with — completely unasserted.
        """
        api = _api_with_frames("a.jpg")
        api.get_task_labels.return_value = [LabelInfo(id=1, name="cat")]
        client = _client_with_api(api)
        df = pd.DataFrame([csv_row("a.jpg", label="cat")])

        assert client.upload_task_annotations(7, df) == 1
        api.get_task_data_meta.assert_called_once_with(7)
        api.get_task_labels.assert_called_once_with(7)


class TestSetTaskJobsStatus:
    def test_requires_stage_or_state(self) -> None:
        client = _client_with_api(MagicMock(spec=CvatApiPort))
        with pytest.raises(Cveta2Error, match="stage"):
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


class TestJobStatusFailure:
    def test_a_rejected_job_patch_fails_the_call(self) -> None:
        """Jobs are patched one request each, now concurrently.

        Swallowing one would report the task complete while a job stayed
        open, which is exactly the state `--complete` exists to prevent.
        """
        api = MagicMock(spec=CvatApiPort)
        api.get_task_jobs.return_value = [
            SimpleNamespace(id=1, start_frame=0, stop_frame=1),
            SimpleNamespace(id=2, start_frame=2, stop_frame=3),
        ]
        api.update_job.side_effect = CvatApiError("nope", status_code=500)
        client = _client_with_api(api)

        with pytest.raises(CvatApiError):
            client.set_task_jobs_status(7, stage="acceptance")

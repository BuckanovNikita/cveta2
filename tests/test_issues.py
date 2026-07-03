"""Unit tests for CVAT issues sync (issue_text / issue_state columns)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pandas as pd

from cveta2._client.context import _build_frame_issues, _TaskContext
from cveta2._client.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawIssue,
    RawShape,
)
from cveta2._client.extractors import _collect_shapes
from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.client import CvatClient, FetchContext, _task_to_records
from cveta2.models import (
    BBoxAnnotation,
    ImageWithoutAnnotations,
    LabelInfo,
    ProjectInfo,
    TaskInfo,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.helpers import CFG, make_bbox, make_fake_client, make_raw_shape, make_task

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task() -> TaskInfo:
    return make_task(100, name="task-issues", subset="train")


def _make_shape(shape_id: int, frame: int) -> RawShape:
    return make_raw_shape(id=shape_id, frame=frame, points=[1.0, 2.0, 3.0, 4.0])


def _make_data_meta(num_frames: int) -> RawDataMeta:
    frames = [
        RawFrame(name=f"img_{i}.jpg", width=640, height=480) for i in range(num_frames)
    ]
    return RawDataMeta(frames=frames)


def _client_with_mocked_sdk(
    sdk: MagicMock, adapter: MagicMock | None = None
) -> CvatClient:
    client = CvatClient(CFG)
    client._sdk_client = sdk
    persistent = adapter if adapter is not None else MagicMock()
    persistent.client = sdk
    client._persistent_api = persistent
    return client


def _single_page(results: list[Any]) -> tuple[SimpleNamespace, SimpleNamespace]:
    return (
        SimpleNamespace(results=results, next=None),
        SimpleNamespace(status=200, msg="OK"),
    )


def _sdk_for_issue_creation(
    num_frames: int, jobs: list[SimpleNamespace]
) -> tuple[MagicMock, MagicMock]:
    sdk = MagicMock()
    sdk.api_client.jobs_api.list_endpoint.call_with_http_info.return_value = (
        _single_page(jobs)
    )
    adapter = MagicMock()
    adapter.get_task_data_meta.return_value = _make_data_meta(num_frames)
    return sdk, adapter


_TWO_JOBS = [
    SimpleNamespace(id=201, start_frame=0, stop_frame=99),
    SimpleNamespace(id=202, start_frame=100, stop_frame=199),
]


# ---------------------------------------------------------------------------
# _build_frame_issues join rules
# ---------------------------------------------------------------------------


class TestBuildFrameIssues:
    def test_no_issues_gives_empty_mapping(self) -> None:
        assert _build_frame_issues([]) == {}

    def test_single_issue_multi_comment_joined_with_semicolon(self) -> None:
        issues = [RawIssue(id=1, frame=0, resolved=False, comments=["a", "b"])]
        assert _build_frame_issues(issues) == {0: ("a; b", "open")}

    def test_resolved_issue_state(self) -> None:
        issues = [RawIssue(id=1, frame=2, resolved=True, comments=["done"])]
        assert _build_frame_issues(issues) == {2: ("done", "resolved")}

    def test_two_issues_on_one_frame_joined_positionally(self) -> None:
        issues = [
            RawIssue(id=1, frame=0, resolved=False, comments=["first"]),
            RawIssue(id=2, frame=0, resolved=True, comments=["second", "more"]),
        ]
        assert _build_frame_issues(issues) == {
            0: ("first | second; more", "open | resolved"),
        }

    def test_issues_on_different_frames(self) -> None:
        issues = [
            RawIssue(id=1, frame=0, resolved=False, comments=["x"]),
            RawIssue(id=2, frame=3, resolved=True, comments=["y"]),
        ]
        assert _build_frame_issues(issues) == {
            0: ("x", "open"),
            3: ("y", "resolved"),
        }

    def test_from_raw_builds_frame_issues(self) -> None:
        ctx = _TaskContext.from_raw(
            _make_task(),
            _make_data_meta(2),
            {1: "car"},
            {},
            [RawIssue(id=1, frame=1, resolved=False, comments=["bad box"])],
        )
        assert ctx.frame_issues == {1: ("bad box", "open")}

    def test_from_raw_without_issues_defaults_empty(self) -> None:
        ctx = _TaskContext.from_raw(_make_task(), _make_data_meta(1), {}, {})
        assert ctx.frame_issues == {}


# ---------------------------------------------------------------------------
# Fetched records carry the columns
# ---------------------------------------------------------------------------


class TestFetchedRecordsCarryIssueColumns:
    def test_collect_shapes_stamps_issue_fields(self) -> None:
        ctx = _TaskContext.from_raw(
            _make_task(),
            _make_data_meta(2),
            {1: "car"},
            {},
            [RawIssue(id=1, frame=0, resolved=False, comments=["плохой бокс"])],
        )
        result = _collect_shapes([_make_shape(1, 0), _make_shape(2, 1)], ctx)
        assert result[0].issue_text == "плохой бокс"
        assert result[0].issue_state == "open"
        assert result[1].issue_text == ""
        assert result[1].issue_state == ""

    def test_task_to_records_stamps_images_without_annotations(self) -> None:
        records, _deleted = _task_to_records(
            _make_task(),
            _make_data_meta(2),
            RawAnnotations(shapes=[_make_shape(1, 0)]),
            {1: "car"},
            {},
            [RawIssue(id=1, frame=1, resolved=True, comments=["a", "b"])],
        )
        without = [r for r in records if isinstance(r, ImageWithoutAnnotations)]
        assert len(without) == 1
        assert without[0].issue_text == "a; b"
        assert without[0].issue_state == "resolved"

    def test_fetch_annotations_with_fake_api_end_to_end(self) -> None:
        task = _make_task()
        fixtures = LoadedFixtures(
            project=ProjectInfo(id=1, name="p"),
            tasks=[task],
            labels=[LabelInfo(id=1, name="car", attributes=[])],
            task_data={
                task.id: (
                    _make_data_meta(2),
                    RawAnnotations(shapes=[_make_shape(1, 0)]),
                ),
            },
            issues={
                task.id: [
                    RawIssue(id=1, frame=0, resolved=False, comments=["открытая"]),
                    RawIssue(id=2, frame=1, resolved=True, comments=["решённая"]),
                ],
            },
        )
        result = make_fake_client(fixtures).fetch_annotations(1)
        boxes = [r for r in result.annotations if isinstance(r, BBoxAnnotation)]
        without = [
            r for r in result.annotations if isinstance(r, ImageWithoutAnnotations)
        ]
        assert boxes[0].issue_text == "открытая"
        assert boxes[0].issue_state == "open"
        assert without[0].issue_text == "решённая"
        assert without[0].issue_state == "resolved"

    def test_fetch_one_task_survives_issues_api_failure(
        self, capture_logs: list[str]
    ) -> None:
        task = _make_task()
        fixtures = LoadedFixtures(
            project=ProjectInfo(id=1, name="p"),
            tasks=[task],
            labels=[LabelInfo(id=1, name="car", attributes=[])],
            task_data={
                task.id: (
                    _make_data_meta(1),
                    RawAnnotations(shapes=[_make_shape(1, 0)]),
                ),
            },
        )

        failing_api = FakeCvatApi(
            fixtures,
            fail_task_ids={task.id},
            fail_status=403,
            fail_methods=("get_task_issues",),
        )
        ctx = FetchContext(tasks=[task], label_names={1: "car"}, attr_names={})
        result = CvatClient.fetch_one_task(failing_api, task, ctx)
        assert result is not None
        assert len(result.annotations) == 1
        first = result.annotations[0]
        assert isinstance(first, BBoxAnnotation)
        assert first.issue_text == ""
        assert first.issue_state == ""
        assert any("issues" in msg for msg in capture_logs)


# ---------------------------------------------------------------------------
# create_task_issues
# ---------------------------------------------------------------------------


class TestCreateTaskIssues:
    def test_frame_to_job_resolution_across_two_jobs(self) -> None:
        sdk, adapter = _sdk_for_issue_creation(200, _TWO_JOBS)
        client = _client_with_mocked_sdk(sdk, adapter)
        df = pd.DataFrame(
            [
                {
                    "image_name": "img_5.jpg",
                    "issue_text": "первая",
                    "issue_state": "new",
                    "bbox_x_tl": 1.0,
                    "bbox_y_tl": 2.0,
                    "bbox_x_br": 3.0,
                    "bbox_y_br": 4.0,
                },
                {
                    "image_name": "img_150.jpg",
                    "issue_text": "вторая",
                    "issue_state": "new",
                    "bbox_x_tl": None,
                    "bbox_y_tl": None,
                    "bbox_x_br": None,
                    "bbox_y_br": None,
                },
            ]
        )

        created = client.create_task_issues(7, df)

        assert created == 2
        calls = sdk.api_client.issues_api.create.call_args_list
        first = calls[0].args[0]
        second = calls[1].args[0]
        assert (first.frame, first.job) == (5, 201)
        assert first.position == [1.0, 2.0, 3.0, 4.0]
        assert first.message == "первая"
        assert (second.frame, second.job) == (150, 202)
        assert second.message == "вторая"

    def test_full_frame_position_falls_back_to_data_meta_dims(self) -> None:
        sdk, adapter = _sdk_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_mocked_sdk(sdk, adapter)
        df = pd.DataFrame(
            [{"image_name": "img_0.jpg", "issue_text": "t", "issue_state": "new"}]
        )

        assert client.create_task_issues(7, df) == 1
        request = sdk.api_client.issues_api.create.call_args.args[0]
        assert request.position == [0.0, 0.0, 640.0, 480.0]

    def test_full_frame_position_prefers_row_dims(self) -> None:
        sdk, adapter = _sdk_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_mocked_sdk(sdk, adapter)
        df = pd.DataFrame(
            [
                {
                    "image_name": "img_0.jpg",
                    "issue_text": "t",
                    "issue_state": "new",
                    "image_width": 800,
                    "image_height": 600,
                }
            ]
        )

        assert client.create_task_issues(7, df) == 1
        request = sdk.api_client.issues_api.create.call_args.args[0]
        assert request.position == [0.0, 0.0, 800.0, 600.0]

    def test_dedupe_on_image_name_and_text(self) -> None:
        sdk, adapter = _sdk_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_mocked_sdk(sdk, adapter)
        row = {"image_name": "img_0.jpg", "issue_text": "same", "issue_state": "new"}
        df = pd.DataFrame([row, row])

        assert client.create_task_issues(7, df) == 1
        assert sdk.api_client.issues_api.create.call_count == 1

    def test_unknown_image_skipped_with_warning(self, capture_logs: list[str]) -> None:
        sdk, adapter = _sdk_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_mocked_sdk(sdk, adapter)
        df = pd.DataFrame(
            [
                {"image_name": "img_0.jpg", "issue_text": "ok", "issue_state": "new"},
                {"image_name": "ghost.jpg", "issue_text": "no", "issue_state": "new"},
            ]
        )

        assert client.create_task_issues(7, df) == 1
        assert sdk.api_client.issues_api.create.call_count == 1
        assert any("ghost.jpg" in msg for msg in capture_logs)

    def test_frame_without_job_skipped_with_warning(
        self, capture_logs: list[str]
    ) -> None:
        jobs = [SimpleNamespace(id=201, start_frame=0, stop_frame=0)]
        sdk, adapter = _sdk_for_issue_creation(2, jobs)
        client = _client_with_mocked_sdk(sdk, adapter)
        df = pd.DataFrame(
            [{"image_name": "img_1.jpg", "issue_text": "t", "issue_state": "new"}]
        )

        assert client.create_task_issues(7, df) == 0
        sdk.api_client.issues_api.create.assert_not_called()
        assert any("img_1.jpg" in msg for msg in capture_logs)

    def test_missing_issue_state_column_returns_zero(self) -> None:
        sdk = MagicMock()
        client = _client_with_mocked_sdk(sdk)
        df = pd.DataFrame([{"image_name": "img_0.jpg"}])

        assert client.create_task_issues(7, df) == 0
        sdk.api_client.issues_api.create.assert_not_called()

    def test_new_state_with_empty_text_ignored(self) -> None:
        sdk = MagicMock()
        client = _client_with_mocked_sdk(sdk)
        df = pd.DataFrame(
            [{"image_name": "img_0.jpg", "issue_text": "", "issue_state": "new"}]
        )

        assert client.create_task_issues(7, df) == 0
        sdk.api_client.issues_api.create.assert_not_called()

    def test_csv_roundtrip_empty_state_read_as_nan_is_handled(
        self, tmp_path: Path
    ) -> None:
        bbox = make_bbox()
        csv_path = tmp_path / "dataset.csv"
        pd.DataFrame([bbox.to_csv_row()]).to_csv(
            csv_path, index=False, encoding="utf-8"
        )
        loaded = pd.read_csv(csv_path)
        assert loaded["issue_state"].isna().all()
        assert loaded["issue_text"].isna().all()

        sdk = MagicMock()
        client = _client_with_mocked_sdk(sdk)

        assert client.create_task_issues(7, loaded) == 0
        sdk.api_client.issues_api.create.assert_not_called()

    def test_open_and_resolved_states_are_not_uploaded(self) -> None:
        sdk = MagicMock()
        client = _client_with_mocked_sdk(sdk)
        df = pd.DataFrame(
            [
                {"image_name": "img_0.jpg", "issue_text": "a", "issue_state": "open"},
                {
                    "image_name": "img_0.jpg",
                    "issue_text": "b",
                    "issue_state": "resolved",
                },
            ]
        )

        assert client.create_task_issues(7, df) == 0
        sdk.api_client.issues_api.create.assert_not_called()


# ---------------------------------------------------------------------------
# SdkCvatApiAdapter.get_task_issues conversion
# ---------------------------------------------------------------------------


class TestGetTaskIssuesAdapter:
    def test_converts_issues_and_comments_in_order(self) -> None:
        sdk = MagicMock()
        issue = SimpleNamespace(id=7, frame=3, resolved=False)
        sdk.api_client.issues_api.list_endpoint.call_with_http_info.return_value = (
            _single_page([issue])
        )
        comments = [
            SimpleNamespace(message="первый"),
            SimpleNamespace(message=None),
            SimpleNamespace(message="третий"),
        ]
        sdk.api_client.comments_api.list_endpoint.call_with_http_info.return_value = (
            _single_page(comments)
        )
        adapter = SdkCvatApiAdapter(sdk)

        result = adapter.get_task_issues(42)

        assert result == [
            RawIssue(id=7, frame=3, resolved=False, comments=["первый", "", "третий"])
        ]
        issues_call = (
            sdk.api_client.issues_api.list_endpoint.call_with_http_info.call_args
        )
        assert issues_call.kwargs["task_id"] == 42
        comments_call = (
            sdk.api_client.comments_api.list_endpoint.call_with_http_info.call_args
        )
        assert comments_call.kwargs["issue_id"] == 7

    def test_no_issues_returns_empty_list(self) -> None:
        sdk = MagicMock()
        sdk.api_client.issues_api.list_endpoint.call_with_http_info.return_value = (
            _single_page([])
        )
        adapter = SdkCvatApiAdapter(sdk)

        assert adapter.get_task_issues(42) == []
        sdk.api_client.comments_api.list_endpoint.call_with_http_info.assert_not_called()


def test_reserved_new_state_not_produced_by_fetch() -> None:
    issues = [RawIssue(id=1, frame=0, resolved=False, comments=["x"])]
    _text, state = _build_frame_issues(issues)[0]
    assert state != "new"

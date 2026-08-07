"""Unit tests for CVAT issues sync (issue_text / issue_state columns)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from cveta2._client.assembly import task_to_records
from cveta2._client.context import _build_frame_issues, _TaskContext
from cveta2._client.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawIssue,
    RawJob,
    RawShape,
)
from cveta2._client.extractors import _collect_shapes
from cveta2._client.ports import CvatApiPort
from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.client import CvatClient, FetchContext
from cveta2.models import (
    BBoxAnnotation,
    ImageWithoutAnnotations,
    LabelInfo,
    ProjectInfo,
    TaskInfo,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.helpers import (
    client_with_api,
    fetch_all_annotations,
    make_bbox,
    make_fake_client,
    make_raw_shape,
    make_task,
    split_records,
)

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


def _client_with_api(api: MagicMock) -> CvatClient:
    return client_with_api(api)


def _single_page(results: list[Any]) -> tuple[SimpleNamespace, SimpleNamespace]:
    return (
        SimpleNamespace(results=results, next=None),
        SimpleNamespace(status=200, msg="OK"),
    )


def _api_for_issue_creation(num_frames: int, jobs: list[RawJob]) -> MagicMock:
    api = MagicMock(spec=CvatApiPort)
    api.get_task_data_meta.return_value = _make_data_meta(num_frames)
    api.get_task_jobs.return_value = jobs
    return api


_BBOX = {
    "bbox_x_tl": 1.0,
    "bbox_y_tl": 2.0,
    "bbox_x_br": 3.0,
    "bbox_y_br": 4.0,
}

_TWO_JOBS = [
    RawJob(id=201, start_frame=0, stop_frame=99),
    RawJob(id=202, start_frame=100, stop_frame=199),
]


def _issue_row(
    image_name: str,
    issue_text: str,
    *,
    issue_state: str = "new",
    bbox: dict[str, float] | None = None,
) -> dict[str, Any]:
    """One create_task_issues input row; ``bbox=_BBOX`` by default, ``{}`` to omit."""
    row: dict[str, Any] = {
        "image_name": image_name,
        "issue_text": issue_text,
        "issue_state": issue_state,
    }
    row.update(_BBOX if bbox is None else bbox)
    return row


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
        records, _deleted = task_to_records(
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
        result = fetch_all_annotations(make_fake_client(fixtures), 1)
        boxes, without = split_records(result)
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
        api = _api_for_issue_creation(200, _TWO_JOBS)
        client = _client_with_api(api)
        df = pd.DataFrame(
            [_issue_row("img_5.jpg", "первая"), _issue_row("img_150.jpg", "вторая")]
        )

        created = client.create_task_issues(7, df)

        assert created == 2
        api.get_task_data_meta.assert_called_once_with(7)
        api.get_task_jobs.assert_called_once_with(7)
        calls = api.create_issue.call_args_list
        first = calls[0].args[0]
        second = calls[1].args[0]
        assert (first.frame, first.job_id) == (5, 201)
        assert first.position == [1.0, 2.0, 3.0, 4.0]
        assert first.message == "первая"
        assert (second.frame, second.job_id) == (150, 202)
        assert second.message == "вторая"

    @pytest.mark.parametrize(
        "partial_coords",
        [{}, {"bbox_x_tl": 1.0, "bbox_y_tl": 2.0}],
        ids=["no-bbox", "partial-bbox"],
    )
    def test_rows_without_full_bbox_skipped_with_warning(
        self, capture_logs: list[str], partial_coords: dict[str, float]
    ) -> None:
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        df = pd.DataFrame([_issue_row("img_0.jpg", "t", bbox=partial_coords)])

        assert client.create_task_issues(7, df) == 0
        api.create_issue.assert_not_called()
        assert any("img_0.jpg" in msg for msg in capture_logs)

    def test_dedupe_on_image_name_and_text(self) -> None:
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        row = _issue_row("img_0.jpg", "same")
        df = pd.DataFrame([row, row])

        assert client.create_task_issues(7, df) == 1
        assert api.create_issue.call_count == 1

    def test_dedupe_ignores_columns_outside_the_key(self) -> None:
        """Rows identical in image, text and bbox collapse to one issue.

        The old dedupe case duplicated a row wholesale, so ``subset=`` could
        be dropped entirely (making ``drop_duplicates`` compare every column)
        without changing the result.  A real dataset carries an
        ``instance_label`` that differs between the co-located boxes.
        """
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        row = _issue_row("img_0.jpg", "same")
        df = pd.DataFrame(
            [{**row, "instance_label": "person"}, {**row, "instance_label": "car"}]
        )

        assert client.create_task_issues(7, df) == 1
        assert api.create_issue.call_count == 1

    def test_same_text_on_different_bboxes_creates_issue_per_bbox(self) -> None:
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        other_bbox = {
            "bbox_x_tl": 10.0,
            "bbox_y_tl": 20.0,
            "bbox_x_br": 30.0,
            "bbox_y_br": 40.0,
        }
        df = pd.DataFrame(
            [
                _issue_row("img_0.jpg", "same"),
                _issue_row("img_0.jpg", "same", bbox=other_bbox),
            ]
        )

        assert client.create_task_issues(7, df) == 2
        positions = [c.args[0].position for c in api.create_issue.call_args_list]
        assert positions == [[1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]]

    def test_unknown_image_skipped_with_warning(self, capture_logs: list[str]) -> None:
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        df = pd.DataFrame(
            [_issue_row("img_0.jpg", "ok"), _issue_row("ghost.jpg", "no")]
        )

        assert client.create_task_issues(7, df) == 1
        assert api.create_issue.call_count == 1
        assert any("ghost.jpg" in msg for msg in capture_logs)

    def test_frame_without_job_skipped_with_warning(
        self, capture_logs: list[str]
    ) -> None:
        jobs = [RawJob(id=201, start_frame=0, stop_frame=0)]
        api = _api_for_issue_creation(2, jobs)
        client = _client_with_api(api)
        df = pd.DataFrame([_issue_row("img_1.jpg", "t")])

        assert client.create_task_issues(7, df) == 0
        api.create_issue.assert_not_called()
        assert any("img_1.jpg" in msg for msg in capture_logs)

    @pytest.mark.parametrize(
        "row",
        [
            {"image_name": "img_0.jpg"},
            {"image_name": "img_0.jpg", "issue_state": "new"},
            {"image_name": "img_0.jpg", "issue_text": "нет состояния"},
        ],
        ids=["neither-column", "state-without-text", "text-without-state"],
    )
    def test_missing_issue_column_returns_zero(self, row: dict[str, Any]) -> None:
        """Both columns are required, not just ``issue_state``.

        Only the "neither" case existed, so the branch that back-fills a
        missing ``issue_text`` was never entered: it could have been filled
        with a non-empty placeholder, turning every ``new`` row into an issue.
        """
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)

        assert client.create_task_issues(7, pd.DataFrame([row])) == 0
        api.create_issue.assert_not_called()

    def test_new_state_with_empty_text_ignored(self) -> None:
        """An empty ``issue_text`` disqualifies the row even when it has a bbox.

        The row previously carried no bbox, so it was dropped downstream for
        the wrong reason: the ``issue_text != ""`` half of the predicate could
        be inverted or compared against a different literal and the count
        stayed 0 regardless.
        """
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        df = pd.DataFrame([_issue_row("img_0.jpg", "")])

        assert client.create_task_issues(7, df) == 0
        api.create_issue.assert_not_called()

    def test_whitespace_only_text_is_not_an_issue(self) -> None:
        """Padding must be stripped before the emptiness check."""
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        df = pd.DataFrame([_issue_row("img_0.jpg", "   ")])

        assert client.create_task_issues(7, df) == 0
        api.create_issue.assert_not_called()

    def test_padding_around_state_and_text_is_stripped(self) -> None:
        """A hand-edited CSV keeps the padding the author typed.

        Nothing previously fed a padded value, so both ``.str.strip()`` calls
        were free to disappear: the state would stop matching ``"new"`` and
        the posted comment would carry the author's stray spaces.
        """
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        df = pd.DataFrame(
            [_issue_row("img_0.jpg", "  плохой бокс  ", issue_state="  new  ")]
        )

        assert client.create_task_issues(7, df) == 1
        assert api.create_issue.call_args.args[0].message == "плохой бокс"

    def test_missing_text_on_a_new_row_is_not_an_issue(self) -> None:
        """``pd.read_csv`` turns a blank ``issue_text`` cell into NaN.

        ``test_csv_roundtrip_empty_state_read_as_nan_is_handled`` had NaN in
        *both* columns, so the row was rejected on the state alone and the
        ``fillna("")`` on the text was never load-bearing — without it NaN
        stringifies to something non-empty and the row gets posted.
        """
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        df = pd.DataFrame([_issue_row("img_0.jpg", "text")])
        df["issue_text"] = None

        assert client.create_task_issues(7, df) == 0
        api.create_issue.assert_not_called()

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

        api = MagicMock(spec=CvatApiPort)
        client = _client_with_api(api)

        assert client.create_task_issues(7, loaded) == 0
        api.create_issue.assert_not_called()

    def test_open_and_resolved_states_are_not_uploaded(self) -> None:
        """Only ``new`` is uploaded; fetched states are already in CVAT.

        These rows previously had no bbox, so they were discarded downstream
        whatever the predicate said — the ``&`` joining state and text could
        become ``|`` and the count stayed 0.  With a full bbox the row would
        actually be posted.
        """
        api = _api_for_issue_creation(1, _TWO_JOBS)
        client = _client_with_api(api)
        df = pd.DataFrame(
            [
                _issue_row("img_0.jpg", "a", issue_state="open"),
                _issue_row("img_0.jpg", "b", issue_state="resolved"),
            ]
        )

        assert client.create_task_issues(7, df) == 0
        api.create_issue.assert_not_called()


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

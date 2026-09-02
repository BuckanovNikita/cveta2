"""Tests for the pure SDK conversion functions in cveta2/_client/sdk_convert.py.

Uses SimpleNamespace to mock CVAT SDK objects without importing cvat_sdk.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from cvat_sdk import Client
from cvat_sdk.api_client.exceptions import ApiAttributeError, ApiException
from cvat_sdk.core.exceptions import BackgroundRequestException

from cveta2._client.dtos import (
    RawAnnotations,
    RawAttribute,
    RawDataMeta,
    RawFrame,
    RawShape,
    UploadTaskSpec,
)
from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2._client.sdk_convert import (
    convert_annotations,
    convert_attributes,
    convert_data_meta,
    convert_label,
    convert_shape,
    convert_task,
    data_meta_from_dict,
    extract_creator_username,
    extract_updated_date,
)
from cveta2._retry import RetryPolicy, _log_retry, configure_retries
from cveta2.exceptions import CvatApiError, Cveta2Error
from cveta2.models import TaskInfo
from tests.helpers import make_sdk_shape

if TYPE_CHECKING:
    from collections.abc import Generator

# ---------------------------------------------------------------------------
# _extract_updated_date
# ---------------------------------------------------------------------------


class TestExtractUpdatedDate:
    def test_string_attr(self) -> None:
        task = SimpleNamespace(updated_date="2026-01-15T10:00:00")
        assert extract_updated_date(task) == "2026-01-15T10:00:00"

    def test_datetime_attr(self) -> None:
        dt = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        task = SimpleNamespace(updated_date=dt)
        assert extract_updated_date(task) == dt.isoformat()

    def test_updated_at_fallback(self) -> None:
        task = type("FakeTask", (), {"updated_at": "2026-02-01T08:00:00"})()
        assert extract_updated_date(task) == "2026-02-01T08:00:00"

    def test_neither_attr_returns_empty(self) -> None:
        task = type("FakeTask", (), {})()
        assert extract_updated_date(task) == ""


# ---------------------------------------------------------------------------
# _convert_label
# ---------------------------------------------------------------------------


class TestConvertLabel:
    def test_basic_label(self) -> None:
        label = SimpleNamespace(id=1, name="car", color="#ff0000", attributes=[])
        result = convert_label(label)
        assert result.id == 1
        assert result.name == "car"
        assert result.color == "#ff0000"
        assert result.attributes == []

    def test_label_with_attributes(self) -> None:
        attr = SimpleNamespace(id=10, name="occluded")
        label = SimpleNamespace(id=2, name="person", color="#00ff00", attributes=[attr])
        result = convert_label(label)
        assert len(result.attributes) == 1
        assert result.attributes[0].name == "occluded"

    def test_label_color_none(self) -> None:
        label = SimpleNamespace(id=3, name="dog", color=None, attributes=None)
        result = convert_label(label)
        assert result.color == ""

    def test_attribute_name_none_falls_back_to_empty(self) -> None:
        """Pin the ``a.name or ""`` fallback inside the attribute comprehension.

        Every other label test gives its attributes a name, so the fallback
        literal was never observed and could be mutated to any other string.
        """
        attr = SimpleNamespace(id=11, name=None)
        label = SimpleNamespace(id=4, name="cat", color="#123456", attributes=[attr])
        result = convert_label(label)
        assert result.attributes[0].name == ""


# ---------------------------------------------------------------------------
# _convert_data_meta
# ---------------------------------------------------------------------------


class TestConvertDataMeta:
    def test_basic_frames(self) -> None:
        frame = SimpleNamespace(name="img.jpg", width=640, height=480)
        data_meta = SimpleNamespace(frames=[frame], deleted_frames=[])
        result = convert_data_meta(data_meta)
        assert len(result.frames) == 1
        assert result.frames[0] == RawFrame(name="img.jpg", width=640, height=480)
        assert result.deleted_frames == []

    def test_deleted_frames(self) -> None:
        data_meta = SimpleNamespace(frames=[], deleted_frames=[0, 3, 5])
        result = convert_data_meta(data_meta)
        assert result.deleted_frames == [0, 3, 5]

    def test_none_frames_and_deleted(self) -> None:
        data_meta = SimpleNamespace(frames=None, deleted_frames=None)
        result = convert_data_meta(data_meta)
        assert result.frames == []
        assert result.deleted_frames == []


# ---------------------------------------------------------------------------
# _data_meta_from_dict
# ---------------------------------------------------------------------------


class TestDataMetaFromDict:
    def test_basic_dict(self) -> None:
        data = {
            "frames": [{"name": "a.jpg", "width": 100, "height": 200}],
            "deleted_frames": [1],
        }
        result = data_meta_from_dict(data)
        assert result.frames == [RawFrame(name="a.jpg", width=100, height=200)]
        assert result.deleted_frames == [1]

    @pytest.mark.parametrize(
        "data",
        [{}, {"frames": None, "deleted_frames": None}],
    )
    def test_empty_or_none_defaults(self, data: dict[str, object]) -> None:
        result = data_meta_from_dict(data)
        assert result == RawDataMeta(frames=[], deleted_frames=[])

    def test_frame_missing_fields_default_to_zero(self) -> None:
        data: dict[str, object] = {"frames": [{}]}
        result = data_meta_from_dict(data)
        assert result.frames[0] == RawFrame(name="", width=0, height=0)


# ---------------------------------------------------------------------------
# _convert_shape
# ---------------------------------------------------------------------------


class TestConvertShape:
    def test_basic_rectangle(self) -> None:
        shape = make_sdk_shape()
        result = convert_shape(shape)
        assert result.type == "rectangle"
        assert result.points == [1.0, 2.0, 3.0, 4.0]
        assert result.label_id == 10

    def test_with_attributes(self) -> None:
        attr = SimpleNamespace(spec_id=5, value="true")
        shape = make_sdk_shape(attributes=[attr])
        result = convert_shape(shape)
        assert result.attributes == [RawAttribute(spec_id=5, value="true")]

    def test_none_attributes(self) -> None:
        shape = make_sdk_shape(attributes=None)
        result = convert_shape(shape)
        assert result.attributes == []

    def test_every_field_carried_over_from_a_fully_populated_shape(self) -> None:
        """Pin every field with a value that differs from the fixture default.

        ``make_sdk_shape`` defaults ``id``/``z_order``/``rotation`` to zero,
        ``occluded`` to ``False`` and ``created_by`` to ``None``, which makes
        ``x or <zero>`` and ``x and <zero>`` produce the same result — those
        mutants were unkillable *as fixtured*, not merely unasserted.  Asserting
        the whole frozen dataclass also covers the fields no earlier test read.
        """
        shape = make_sdk_shape(
            id=77,
            type=SimpleNamespace(value="polygon"),
            frame=4,
            label_id=12,
            points=[1.5, 2.5, 3.5, 4.5],
            occluded=True,
            z_order=3,
            rotation=45.5,
            source="auto",
            attributes=[SimpleNamespace(spec_id=8, value="yes")],
            created_by=SimpleNamespace(username="alice"),
        )
        assert convert_shape(shape) == RawShape(
            id=77,
            type="polygon",
            frame=4,
            label_id=12,
            points=[1.5, 2.5, 3.5, 4.5],
            occluded=True,
            z_order=3,
            rotation=45.5,
            source="auto",
            attributes=[RawAttribute(spec_id=8, value="yes")],
            created_by="alice",
        )

    def test_falsy_sdk_fields_take_their_documented_defaults(self) -> None:
        """Pin the other side of every ``or`` fallback in ``convert_shape``.

        The truthy test above cannot see the fallback literals at all: with a
        non-empty ``source`` the expression ``source or ""`` yields the same
        value however the literal is mutated.  A shape whose optional fields
        are all unset is the only input that observes them.
        """
        shape = make_sdk_shape(
            id=None,
            type="",
            frame=6,
            label_id=13,
            points=None,
            occluded=False,
            z_order=None,
            rotation=None,
            source=None,
            attributes=None,
            created_by=None,
            owner=None,
        )
        assert convert_shape(shape) == RawShape(
            id=0,
            type="",
            frame=6,
            label_id=13,
            points=[],
            occluded=False,
            z_order=0,
            rotation=0.0,
            source="",
            attributes=[],
            created_by="",
        )


# ---------------------------------------------------------------------------
# convert_annotations
# ---------------------------------------------------------------------------


class TestConvertAnnotations:
    """No test called ``convert_annotations`` at all before these."""

    def test_converts_every_shape(self) -> None:
        labeled_data = SimpleNamespace(
            shapes=[make_sdk_shape(id=3, frame=1), make_sdk_shape(id=4, frame=2)]
        )
        result = convert_annotations(labeled_data)
        assert [(s.id, s.frame) for s in result.shapes] == [(3, 1), (4, 2)]

    def test_none_shapes_becomes_empty_list(self) -> None:
        """A task with no annotations must yield an empty list, never ``None``."""
        assert convert_annotations(SimpleNamespace(shapes=None)) == RawAnnotations(
            shapes=[]
        )


# ---------------------------------------------------------------------------
# convert_task
# ---------------------------------------------------------------------------


class TestConvertTask:
    """No test called ``convert_task`` at all before these."""

    def test_populated_task_maps_every_field(self) -> None:
        task = SimpleNamespace(
            id=42,
            name="task-a",
            status="completed",
            subset="train",
            updated_date="2026-05-01T10:00:00",
            project_id=7,
        )
        assert convert_task(task) == TaskInfo(
            id=42,
            name="task-a",
            status="completed",
            subset="train",
            updated_date="2026-05-01T10:00:00",
            project_id=7,
        )

    def test_project_id_read_as_int_from_a_string_value(self) -> None:
        """The SDK may hand ``project_id`` back as a string, so ``int()`` matters."""
        task = SimpleNamespace(
            id=1,
            name="t",
            status="annotation",
            subset="",
            updated_date="",
            project_id="9",
        )
        assert convert_task(task).project_id == 9

    def test_unset_optional_fields_take_their_documented_defaults(self) -> None:
        """Pin the falsy side of every ``or ""`` and the missing-``project_id`` path.

        A ``TaskRead`` without ``project_id`` is what forces the three-argument
        ``getattr``: dropping its default turns this case into an
        ``AttributeError`` instead of ``project_id=None``.
        """
        task = SimpleNamespace(
            id=1, name=None, status=None, subset=None, updated_date=None
        )
        assert convert_task(task) == TaskInfo(
            id=1,
            name="",
            status="",
            subset="",
            updated_date="",
            project_id=None,
        )


# ---------------------------------------------------------------------------
# _convert_attributes
# ---------------------------------------------------------------------------


class TestConvertAttributes:
    def test_none_returns_empty(self) -> None:
        assert convert_attributes(None) == []

    def test_empty_list_returns_empty(self) -> None:
        assert convert_attributes([]) == []

    def test_converts_attrs(self) -> None:
        attrs = [
            SimpleNamespace(spec_id=1, value="yes"),
            SimpleNamespace(spec_id=2, value=None),
        ]
        result = convert_attributes(attrs)
        assert result == [
            RawAttribute(spec_id=1, value="yes"),
            RawAttribute(spec_id=2, value=""),
        ]


# ---------------------------------------------------------------------------
# _extract_creator_username
# ---------------------------------------------------------------------------


class TestExtractCreatorUsername:
    def test_user_with_username(self) -> None:
        shape = SimpleNamespace(created_by=SimpleNamespace(username="alice"))
        assert extract_creator_username(shape) == "alice"

    def test_user_with_name_fallback(self) -> None:
        user = type("User", (), {"name": "bob"})()
        shape = SimpleNamespace(created_by=user)
        assert extract_creator_username(shape) == "bob"

    def test_owner_fallback(self) -> None:
        shape = type(
            "Shape",
            (),
            {
                "created_by": None,
                "owner": SimpleNamespace(username="charlie"),
            },
        )()
        assert extract_creator_username(shape) == "charlie"

    def test_dict_user(self) -> None:
        shape = SimpleNamespace(created_by={"username": "dave"})
        assert extract_creator_username(shape) == "dave"

    def test_dict_user_name_key(self) -> None:
        shape = SimpleNamespace(created_by={"name": "eve"})
        assert extract_creator_username(shape) == "eve"

    def test_no_user_returns_empty(self) -> None:
        shape = type("Shape", (), {})()
        assert extract_creator_username(shape) == ""

    def test_dict_user_without_name_keys_returns_empty(self) -> None:
        """Pin the fallback of the dict branch, which no earlier test reached."""
        shape = SimpleNamespace(created_by={"id": 3})
        assert extract_creator_username(shape) == ""

    def test_object_user_without_name_attributes_returns_empty(self) -> None:
        """Pin the final ``return ""``.

        Reached only by a *present* creator object that exposes neither
        ``username`` nor ``name`` and is not a dict — every earlier test either
        found a name or had no creator at all, so this line never ran.
        """
        shape = SimpleNamespace(created_by=SimpleNamespace(username=None, name=None))
        assert extract_creator_username(shape) == ""


# ---------------------------------------------------------------------------
# _log_retry
# ---------------------------------------------------------------------------


def test_log_retry_does_not_crash() -> None:
    state = MagicMock()
    state.outcome.exception.return_value = RuntimeError("connection lost")
    state.attempt_number = 2
    _log_retry("CVAT API", state)


class _TaskWithoutSize:
    """A ``TaskRead`` the server sent with no ``size`` field at all.

    The generated SDK raises on the access rather than returning None.
    """

    @property
    def size(self) -> int:
        raise ApiAttributeError("TaskRead has no attribute 'size'")


class TestGetTaskSize:
    """The read-back `upload --resume` decides task reuse from."""

    @staticmethod
    def _adapter_for(task: object) -> SdkCvatApiAdapter:
        client = MagicMock()
        client.tasks.retrieve.return_value = task
        return SdkCvatApiAdapter(client)

    def test_a_task_with_frames_reports_them(self) -> None:
        assert self._adapter_for(SimpleNamespace(size=8)).get_task_size(1) == 8

    def test_a_task_whose_data_never_attached_reports_zero(self) -> None:
        """CVAT omits ``size`` entirely, and the SDK raises on the access.

        That is the state a killed upload leaves behind, so treating it as
        an error would make the recovery path unreachable — found against a
        live server, where the attribute is simply absent.
        """
        assert self._adapter_for(_TaskWithoutSize()).get_task_size(1) == 0

    def test_a_null_size_reports_zero(self) -> None:
        """The other spelling of "no data yet" some versions return."""
        assert self._adapter_for(SimpleNamespace(size=None)).get_task_size(1) == 0


# ---------------------------------------------------------------------------
# attach_task_data
# ---------------------------------------------------------------------------


class TestAttachTaskData:
    """The retry unit around the data call, and what escapes it."""

    @pytest.fixture(autouse=True)
    def _cheap_retries(self) -> Generator[None, None, None]:
        attempts, max_wait = RetryPolicy.attempts, RetryPolicy.max_wait
        configure_retries(attempts=3, max_wait=0.01)
        yield
        configure_retries(attempts, max_wait)

    @staticmethod
    def _adapter(client: MagicMock) -> SdkCvatApiAdapter:
        client.api_client.tasks_api.create_data.return_value = (
            SimpleNamespace(rq_id="rq-1"),
            None,
        )
        return SdkCvatApiAdapter(client)

    @staticmethod
    def _spec() -> UploadTaskSpec:
        return UploadTaskSpec(
            project_id=1,
            name="task",
            server_files=["a.jpg"],
            cloud_storage_id=7,
        )

    def test_a_throttled_size_read_does_not_re_upload_the_data(self) -> None:
        """The size read is for a log line; retrying it must not redo the write.

        ``create_data`` is not idempotent, so a second pass attaches the
        images again to a task CVAT has already finished processing.
        """
        client = MagicMock()
        client.tasks.retrieve.side_effect = CvatApiError("429", status_code=429)
        adapter = self._adapter(client)

        adapter.attach_task_data(1, self._spec())

        assert client.api_client.tasks_api.create_data.call_count == 1

    def test_a_throttled_status_poll_does_not_re_upload_the_data(self) -> None:
        """Polling the request status is a read; a 429 there must only re-poll.

        Retrying the whole attach would re-issue ``create_data`` on a task
        that already holds its images, which CVAT rejects.
        """
        client = MagicMock()
        client.wait_for_completion.side_effect = [ApiException(status=429), None]
        adapter = self._adapter(client)

        adapter.attach_task_data(1, self._spec())

        assert client.api_client.tasks_api.create_data.call_count == 1
        assert client.wait_for_completion.call_count == 2

    def test_a_throttled_data_post_is_retried(self) -> None:
        """A 429 on the data POST itself is a refusal, so the write is repeated."""
        client = MagicMock()
        adapter = self._adapter(client)
        client.api_client.tasks_api.create_data.side_effect = [
            ApiException(status=429),
            (SimpleNamespace(rq_id="rq-1"), None),
        ]

        adapter.attach_task_data(1, self._spec())

        assert client.api_client.tasks_api.create_data.call_count == 2
        client.wait_for_completion.assert_called_once()
        assert client.wait_for_completion.call_args.args == ("rq-1",)

    def test_a_processing_failure_raises_a_domain_error(self) -> None:
        """``CliApp`` catches only ``Cveta2Error``; anything else is a traceback."""
        client = MagicMock()
        client.wait_for_completion.side_effect = BackgroundRequestException("boom")
        adapter = self._adapter(client)

        with pytest.raises(Cveta2Error, match="обработка данных не удалась"):
            adapter.attach_task_data(1, self._spec())

        assert client.wait_for_completion.call_count == 1


# ---------------------------------------------------------------------------
# set_organization
# ---------------------------------------------------------------------------


class TestSetOrganization:
    """The port's ``None`` is the personal workspace, not "no org context".

    ``cvat_sdk`` drops the ``X-Organization`` header on ``None``, and CVAT
    then lists resources from every organization the user can access; an
    empty header is what scopes requests to the sandbox.
    """

    @pytest.fixture
    def sdk_client(self) -> Generator[Client, None, None]:
        with Client("http://localhost:1", check_server_version=False) as client:
            yield client

    def test_none_sends_an_empty_organization_header(self, sdk_client: Client) -> None:
        SdkCvatApiAdapter(sdk_client).set_organization(None)

        assert sdk_client.api_client.default_headers["X-Organization"] == ""

    def test_a_slug_is_sent_verbatim(self, sdk_client: Client) -> None:
        SdkCvatApiAdapter(sdk_client).set_organization("acme")

        assert sdk_client.api_client.default_headers["X-Organization"] == "acme"

"""Tests for static conversion methods in cveta2/_client/sdk_adapter.py.

Uses SimpleNamespace to mock CVAT SDK objects without importing cvat_sdk.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cveta2._client.dtos import RawAttribute, RawDataMeta, RawFrame
from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2._retry import _log_retry
from tests.helpers import make_sdk_shape

# ---------------------------------------------------------------------------
# _extract_updated_date
# ---------------------------------------------------------------------------


class TestExtractUpdatedDate:
    def test_string_attr(self) -> None:
        task = SimpleNamespace(updated_date="2026-01-15T10:00:00")
        assert SdkCvatApiAdapter._extract_updated_date(task) == "2026-01-15T10:00:00"

    def test_datetime_attr(self) -> None:
        dt = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        task = SimpleNamespace(updated_date=dt)
        assert SdkCvatApiAdapter._extract_updated_date(task) == dt.isoformat()

    def test_updated_at_fallback(self) -> None:
        task = type("FakeTask", (), {"updated_at": "2026-02-01T08:00:00"})()
        assert SdkCvatApiAdapter._extract_updated_date(task) == "2026-02-01T08:00:00"

    def test_neither_attr_returns_empty(self) -> None:
        task = type("FakeTask", (), {})()
        assert SdkCvatApiAdapter._extract_updated_date(task) == ""


# ---------------------------------------------------------------------------
# _convert_label
# ---------------------------------------------------------------------------


class TestConvertLabel:
    def test_basic_label(self) -> None:
        label = SimpleNamespace(id=1, name="car", color="#ff0000", attributes=[])
        result = SdkCvatApiAdapter._convert_label(label)
        assert result.id == 1
        assert result.name == "car"
        assert result.color == "#ff0000"
        assert result.attributes == []

    def test_label_with_attributes(self) -> None:
        attr = SimpleNamespace(id=10, name="occluded")
        label = SimpleNamespace(id=2, name="person", color="#00ff00", attributes=[attr])
        result = SdkCvatApiAdapter._convert_label(label)
        assert len(result.attributes) == 1
        assert result.attributes[0].name == "occluded"

    def test_label_color_none(self) -> None:
        label = SimpleNamespace(id=3, name="dog", color=None, attributes=None)
        result = SdkCvatApiAdapter._convert_label(label)
        assert result.color == ""


# ---------------------------------------------------------------------------
# _convert_data_meta
# ---------------------------------------------------------------------------


class TestConvertDataMeta:
    def test_basic_frames(self) -> None:
        frame = SimpleNamespace(name="img.jpg", width=640, height=480)
        data_meta = SimpleNamespace(frames=[frame], deleted_frames=[])
        result = SdkCvatApiAdapter._convert_data_meta(data_meta)
        assert len(result.frames) == 1
        assert result.frames[0] == RawFrame(name="img.jpg", width=640, height=480)
        assert result.deleted_frames == []

    def test_deleted_frames(self) -> None:
        data_meta = SimpleNamespace(frames=[], deleted_frames=[0, 3, 5])
        result = SdkCvatApiAdapter._convert_data_meta(data_meta)
        assert result.deleted_frames == [0, 3, 5]

    def test_none_frames_and_deleted(self) -> None:
        data_meta = SimpleNamespace(frames=None, deleted_frames=None)
        result = SdkCvatApiAdapter._convert_data_meta(data_meta)
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
        result = SdkCvatApiAdapter._data_meta_from_dict(data)
        assert result.frames == [RawFrame(name="a.jpg", width=100, height=200)]
        assert result.deleted_frames == [1]

    @pytest.mark.parametrize(
        "data",
        [{}, {"frames": None, "deleted_frames": None}],
    )
    def test_empty_or_none_defaults(self, data: dict[str, object]) -> None:
        result = SdkCvatApiAdapter._data_meta_from_dict(data)
        assert result == RawDataMeta(frames=[], deleted_frames=[])

    def test_frame_missing_fields_default_to_zero(self) -> None:
        data: dict[str, object] = {"frames": [{}]}
        result = SdkCvatApiAdapter._data_meta_from_dict(data)
        assert result.frames[0] == RawFrame(name="", width=0, height=0)


# ---------------------------------------------------------------------------
# _convert_shape
# ---------------------------------------------------------------------------


class TestConvertShape:
    def test_basic_rectangle(self) -> None:
        shape = make_sdk_shape()
        result = SdkCvatApiAdapter._convert_shape(shape)
        assert result.type == "rectangle"
        assert result.points == [1.0, 2.0, 3.0, 4.0]
        assert result.label_id == 10

    def test_with_attributes(self) -> None:
        attr = SimpleNamespace(spec_id=5, value="true")
        shape = make_sdk_shape(attributes=[attr])
        result = SdkCvatApiAdapter._convert_shape(shape)
        assert result.attributes == [RawAttribute(spec_id=5, value="true")]

    def test_none_attributes(self) -> None:
        shape = make_sdk_shape(attributes=None)
        result = SdkCvatApiAdapter._convert_shape(shape)
        assert result.attributes == []


# ---------------------------------------------------------------------------
# _convert_attributes
# ---------------------------------------------------------------------------


class TestConvertAttributes:
    def test_none_returns_empty(self) -> None:
        assert SdkCvatApiAdapter._convert_attributes(None) == []

    def test_empty_list_returns_empty(self) -> None:
        assert SdkCvatApiAdapter._convert_attributes([]) == []

    def test_converts_attrs(self) -> None:
        attrs = [
            SimpleNamespace(spec_id=1, value="yes"),
            SimpleNamespace(spec_id=2, value=None),
        ]
        result = SdkCvatApiAdapter._convert_attributes(attrs)
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
        assert SdkCvatApiAdapter._extract_creator_username(shape) == "alice"

    def test_user_with_name_fallback(self) -> None:
        user = type("User", (), {"name": "bob"})()
        shape = SimpleNamespace(created_by=user)
        assert SdkCvatApiAdapter._extract_creator_username(shape) == "bob"

    def test_owner_fallback(self) -> None:
        shape = type(
            "Shape",
            (),
            {
                "created_by": None,
                "owner": SimpleNamespace(username="charlie"),
            },
        )()
        assert SdkCvatApiAdapter._extract_creator_username(shape) == "charlie"

    def test_dict_user(self) -> None:
        shape = SimpleNamespace(created_by={"username": "dave"})
        assert SdkCvatApiAdapter._extract_creator_username(shape) == "dave"

    def test_dict_user_name_key(self) -> None:
        shape = SimpleNamespace(created_by={"name": "eve"})
        assert SdkCvatApiAdapter._extract_creator_username(shape) == "eve"

    def test_no_user_returns_empty(self) -> None:
        shape = type("Shape", (), {})()
        assert SdkCvatApiAdapter._extract_creator_username(shape) == ""


# ---------------------------------------------------------------------------
# _log_retry
# ---------------------------------------------------------------------------


def test_log_retry_does_not_crash() -> None:
    state = MagicMock()
    state.outcome.exception.return_value = RuntimeError("connection lost")
    state.attempt_number = 2
    _log_retry("CVAT API", state)

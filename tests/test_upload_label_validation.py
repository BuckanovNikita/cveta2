"""Tests for label validation in the upload command."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cveta2.exceptions import LabelsMismatchError
from cveta2.models import LabelInfo
from cveta2.services.upload import validate_labels


class TestLabelsMismatchError:
    """Tests for the LabelsMismatchError exception."""

    def test_unknown_labels_stored(self) -> None:
        err = LabelsMismatchError(
            unknown_labels=["cat", "dog"],
            project_name="my_project",
            available_labels=["car", "person"],
        )
        assert err.unknown_labels == ["cat", "dog"]

    def test_available_labels_stored(self) -> None:
        err = LabelsMismatchError(
            unknown_labels=["cat"],
            project_name="my_project",
            available_labels=["car", "person"],
        )
        assert err.available_labels == ["car", "person"]

    @pytest.mark.parametrize(
        "fragment",
        ["cat", "dog", "my_project", "car", "person"],
    )
    def test_message_contains_fragment(self, fragment: str) -> None:
        err = LabelsMismatchError(
            unknown_labels=["cat", "dog"],
            project_name="my_project",
            available_labels=["car", "person"],
        )
        assert fragment in str(err)


def _client_with_labels(names: set[str]) -> MagicMock:
    client = MagicMock()
    client.get_project_labels.return_value = [
        LabelInfo(id=i, name=name, attributes=[])
        for i, name in enumerate(sorted(names))
    ]
    return client


class TestUploadLabelValidation:
    """Tests for _validate_labels in the upload command."""

    def test_labels_match_no_error(self) -> None:
        validate_labels(
            _client_with_labels({"car", "person", "truck"}),
            1,
            "test_project",
            ["car", "person"],
        )

    def test_labels_mismatch_raises(self) -> None:
        with pytest.raises(LabelsMismatchError) as exc_info:
            validate_labels(
                _client_with_labels({"car", "person"}),
                1,
                "test_project",
                ["car", "cat", "dog"],
            )
        assert exc_info.value.unknown_labels == ["cat", "dog"]

    def test_empty_real_labels_no_error(self) -> None:
        client = _client_with_labels({"car", "person"})
        validate_labels(client, 1, "test_project", [])
        client.get_project_labels.assert_not_called()

    def test_labels_are_looked_up_for_the_requested_project(self) -> None:
        """The project id must reach ``get_project_labels``.

        ``_client_with_labels`` answers every id the same way, so a call
        that passed ``None`` instead of the project id looked identical.
        """
        client = MagicMock()
        client.get_project_labels.side_effect = lambda project_id: (
            [LabelInfo(id=1, name="car", attributes=[])] if project_id == 1 else []
        )

        validate_labels(client, 1, "test_project", ["car"])

        with pytest.raises(LabelsMismatchError):
            validate_labels(client, 2, "test_project", ["car"])

    def test_mismatch_error_names_the_project(self) -> None:
        """The raised error must carry the project name it was given."""
        with pytest.raises(LabelsMismatchError, match="test_project"):
            validate_labels(
                _client_with_labels({"car"}),
                1,
                "test_project",
                ["unknown"],
            )

    def test_mismatch_error_lists_available(self) -> None:
        with pytest.raises(LabelsMismatchError) as exc_info:
            validate_labels(
                _client_with_labels({"car", "person"}),
                1,
                "test_project",
                ["unknown"],
            )
        assert exc_info.value.available_labels == ["car", "person"]

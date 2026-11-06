"""Tests for label validation in the upload use case."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cveta2.application.use_cases.upload import validate_labels
from cveta2.domain.errors import LabelsMismatchError
from cveta2.domain.models import LabelInfo


def _client_with_labels(names: set[str], *, project_id: int = 1) -> MagicMock:
    """Answer ``get_project_labels`` with *names* for *project_id* only."""
    labels = [
        LabelInfo(id=i, name=name, attributes=[])
        for i, name in enumerate(sorted(names))
    ]
    client = MagicMock()
    client.get_project_labels.side_effect = lambda requested: (
        labels if requested == project_id else []
    )
    return client


def test_known_labels_pass_only_for_the_requested_project() -> None:
    """The project id must reach ``get_project_labels``."""
    client = _client_with_labels({"car", "person", "truck"})

    validate_labels(client, 1, "test_project", ["car", "person"])

    with pytest.raises(LabelsMismatchError):
        validate_labels(client, 2, "test_project", ["car"])


def test_mismatch_error_carries_and_renders_every_diagnostic() -> None:
    with pytest.raises(LabelsMismatchError) as exc_info:
        validate_labels(
            _client_with_labels({"car", "person"}),
            1,
            "test_project",
            ["car", "cat", "dog"],
        )
    assert exc_info.value.unknown_labels == ["cat", "dog"]
    assert exc_info.value.available_labels == ["car", "person"]
    message = str(exc_info.value)
    assert all(
        fragment in message
        for fragment in ("cat", "dog", "test_project", "car", "person")
    )


def test_empty_real_labels_no_error() -> None:
    client = _client_with_labels({"car", "person"})
    validate_labels(client, 1, "test_project", [])
    client.get_project_labels.assert_not_called()

"""Tests for label validation in the upload command."""

from __future__ import annotations

import pytest

from cveta2.exceptions import LabelsMismatchError


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

    def test_message_contains_unknown_labels(self) -> None:
        err = LabelsMismatchError(
            unknown_labels=["cat", "dog"],
            project_name="my_project",
            available_labels=["car", "person"],
        )
        msg = str(err)
        assert "cat" in msg
        assert "dog" in msg

    def test_message_contains_project_name(self) -> None:
        err = LabelsMismatchError(
            unknown_labels=["cat"],
            project_name="my_project",
            available_labels=["car"],
        )
        assert "my_project" in str(err)

    def test_message_contains_available_labels(self) -> None:
        err = LabelsMismatchError(
            unknown_labels=["cat"],
            project_name="my_project",
            available_labels=["car", "person"],
        )
        msg = str(err)
        assert "car" in msg
        assert "person" in msg

    def test_is_cveta2_error(self) -> None:
        from cveta2.exceptions import Cveta2Error

        err = LabelsMismatchError(
            unknown_labels=["cat"],
            project_name="p",
            available_labels=["car"],
        )
        assert isinstance(err, Cveta2Error)


class TestUploadLabelValidation:
    """Tests for the label validation logic in upload command.

    These tests exercise the validation logic by simulating what
    ``run_upload`` does: comparing CSV labels against project labels.
    """

    @staticmethod
    def _validate(
        real_labels: list[str],
        project_label_names: set[str],
        project_name: str = "test_project",
    ) -> None:
        """Reproduce the validation logic from run_upload."""
        if real_labels:
            unknown_labels = sorted(set(real_labels) - project_label_names)
            if unknown_labels:
                raise LabelsMismatchError(
                    unknown_labels=unknown_labels,
                    project_name=project_name,
                    available_labels=sorted(project_label_names),
                )

    def test_labels_match_no_error(self) -> None:
        self._validate(
            real_labels=["car", "person"],
            project_label_names={"car", "person", "truck"},
        )

    def test_labels_mismatch_raises(self) -> None:
        with pytest.raises(LabelsMismatchError) as exc_info:
            self._validate(
                real_labels=["car", "cat", "dog"],
                project_label_names={"car", "person"},
            )
        assert exc_info.value.unknown_labels == ["cat", "dog"]

    def test_empty_real_labels_no_error(self) -> None:
        self._validate(
            real_labels=[],
            project_label_names={"car", "person"},
        )

    def test_mismatch_error_lists_available(self) -> None:
        with pytest.raises(LabelsMismatchError) as exc_info:
            self._validate(
                real_labels=["unknown"],
                project_label_names={"car", "person"},
            )
        assert exc_info.value.available_labels == ["car", "person"]

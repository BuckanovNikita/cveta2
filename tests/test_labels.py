"""Tests for the ``cveta2 labels`` command and related client methods."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

from cveta2.cli import CliApp
from cveta2.client import CvatClient
from cveta2.commands.labels import (
    _interactive_add,
    _interactive_delete,
    _interactive_recolor,
    _interactive_rename,
    _print_labels,
    _validate_hex_color,
)
from cveta2.config import CvatConfig
from cveta2.exceptions import InteractiveModeRequiredError
from cveta2.models import LabelAttributeInfo, LabelInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import (
    FakeProjectConfig,
    LoadedFixtures,
    build_fake_project,
    task_indices_by_names,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CFG = CvatConfig()

_LABELS = [
    LabelInfo(id=1, name="cat", attributes=[], color="#ff0000"),
    LabelInfo(id=2, name="dog", attributes=[LabelAttributeInfo(id=10, name="breed")]),
    LabelInfo(
        id=3,
        name="bird",
        attributes=[
            LabelAttributeInfo(id=11, name="species"),
            LabelAttributeInfo(id=12, name="color"),
        ],
        color="#00ff00",
    ),
]


def _build(
    base: LoadedFixtures,
    task_names: list[str],
    statuses: list[str] | None = None,
) -> LoadedFixtures:
    indices = task_indices_by_names(base.tasks, task_names)
    config = FakeProjectConfig(
        task_indices=indices,
        task_statuses=statuses if statuses is not None else "keep",
    )
    return build_fake_project(base, config)


def _write_config(path: Path) -> None:
    data = {
        "cvat": {
            "host": "http://localhost:8080",
            "token": "test-token",
        },
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _mock_client_ctx(
    labels: list[LabelInfo] | None = None,
) -> MagicMock:
    """Build a mock CvatClient for CLI tests."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.resolve_project_id.return_value = 1
    client.get_project_labels.return_value = labels or []
    client.count_label_usage.return_value = {}
    return client


def _setup_sdk_mock(client: CvatClient) -> MagicMock:
    """Set up mocked SDK internals for update_project_labels tests.

    Returns the mock SDK object whose ``api_client.projects_api``
    can be asserted on.
    """
    mock_sdk = MagicMock()
    # Satisfy _require_sdk() check
    object.__setattr__(client, "_sdk_client", MagicMock())
    api = MagicMock()
    api.client = mock_sdk
    object.__setattr__(client, "_persistent_api", api)
    return mock_sdk


# ---------------------------------------------------------------------------
# LabelInfo.format_display
# ---------------------------------------------------------------------------


def test_format_label_simple() -> None:
    label = LabelInfo(id=1, name="cat", attributes=[])
    result = label.format_display()
    assert "'cat'" in result
    assert "id=1" in result


def test_format_label_with_color() -> None:
    label = LabelInfo(id=1, name="cat", attributes=[], color="#ff0000")
    result = label.format_display()
    assert "цвет=#ff0000" in result


def test_format_label_with_attributes() -> None:
    label = LabelInfo(
        id=2,
        name="dog",
        attributes=[
            LabelAttributeInfo(id=10, name="breed"),
            LabelAttributeInfo(id=11, name="size"),
        ],
    )
    result = label.format_display()
    assert "атрибуты: breed, size" in result


def test_format_label_no_color_no_attrs() -> None:
    label = LabelInfo(id=5, name="fish", attributes=[])
    result = label.format_display()
    assert "цвет" not in result
    assert "атрибуты" not in result


# ---------------------------------------------------------------------------
# _print_labels
# ---------------------------------------------------------------------------


def test_print_labels_empty() -> None:
    _print_labels([], "test-project")


def test_print_labels_with_data() -> None:
    _print_labels(_LABELS, "test-project")


# ---------------------------------------------------------------------------
# CvatClient.get_project_labels (via FakeCvatApi)
# ---------------------------------------------------------------------------


def test_get_project_labels_returns_fixture_labels(
    coco8_fixtures: LoadedFixtures,
) -> None:
    fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
    client = CvatClient(_CFG, api=FakeCvatApi(fake))
    labels = client.get_project_labels(fake.project.id)
    assert len(labels) == len(fake.labels)
    assert all(isinstance(lbl, LabelInfo) for lbl in labels)
    label_names = {lbl.name for lbl in labels}
    expected_names = {lbl.name for lbl in fake.labels}
    assert label_names == expected_names


# ---------------------------------------------------------------------------
# CvatClient.count_label_usage (via FakeCvatApi)
# ---------------------------------------------------------------------------


def test_count_label_usage_shapes_per_label(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """Normal task has shapes; count_label_usage aggregates them."""
    fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
    client = CvatClient(_CFG, api=FakeCvatApi(fake))
    counts = client.count_label_usage(fake.project.id)
    total = sum(counts.values())
    assert total == 30


def test_count_label_usage_empty_task(
    coco8_fixtures: LoadedFixtures,
) -> None:
    fake = _build(coco8_fixtures, ["all-empty"], statuses=["completed"])
    client = CvatClient(_CFG, api=FakeCvatApi(fake))
    counts = client.count_label_usage(fake.project.id)
    assert sum(counts.values()) == 0


def test_count_label_usage_multiple_tasks(
    coco8_fixtures: LoadedFixtures,
) -> None:
    fake = _build(
        coco8_fixtures,
        ["normal", "all-bboxes-moved"],
        statuses=["completed", "completed"],
    )
    client = CvatClient(_CFG, api=FakeCvatApi(fake))
    counts = client.count_label_usage(fake.project.id)
    total = sum(counts.values())
    assert total > 30


def test_count_label_usage_ids_match_labels(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """All label_ids in usage come from the project's labels."""
    fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
    client = CvatClient(_CFG, api=FakeCvatApi(fake))
    counts = client.count_label_usage(fake.project.id)
    label_ids = {lbl.id for lbl in fake.labels}
    for lid in counts:
        assert lid in label_ids


def test_count_label_usage_deleted_frames_counted(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """Shapes on deleted frames are still counted (they exist in CVAT)."""
    fake = _build(coco8_fixtures, ["all-removed"], statuses=["completed"])
    client = CvatClient(_CFG, api=FakeCvatApi(fake))
    counts = client.count_label_usage(fake.project.id)
    assert sum(counts.values()) == 30


# ---------------------------------------------------------------------------
# CvatClient.update_project_labels (mock SDK)
# ---------------------------------------------------------------------------


def test_update_labels_no_ops_does_nothing() -> None:
    """Empty add/rename/delete does not call the SDK."""
    client = CvatClient(_CFG)
    mock_sdk = _setup_sdk_mock(client)

    client.update_project_labels(1)
    mock_sdk.api_client.projects_api.partial_update.assert_not_called()


def test_update_labels_add_calls_partial_update() -> None:
    client = CvatClient(_CFG)
    mock_sdk = _setup_sdk_mock(client)

    client.update_project_labels(42, add=["new_label"])
    mock_sdk.api_client.projects_api.partial_update.assert_called_once()
    call_args = mock_sdk.api_client.projects_api.partial_update.call_args
    assert call_args[0][0] == 42


def test_update_labels_delete_calls_partial_update() -> None:
    client = CvatClient(_CFG)
    mock_sdk = _setup_sdk_mock(client)

    client.update_project_labels(42, delete=[1, 2])
    mock_sdk.api_client.projects_api.partial_update.assert_called_once()


def test_update_labels_rename_calls_partial_update() -> None:
    client = CvatClient(_CFG)
    mock_sdk = _setup_sdk_mock(client)

    client.update_project_labels(42, rename={1: "renamed"})
    mock_sdk.api_client.projects_api.partial_update.assert_called_once()


def test_update_labels_requires_context_manager() -> None:
    client = CvatClient(_CFG)
    with pytest.raises(RuntimeError, match="context manager"):
        client.update_project_labels(1, add=["x"])


# ---------------------------------------------------------------------------
# Labels CLI (--list, non-interactive)
# ---------------------------------------------------------------------------


def test_cli_labels_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx(labels=_LABELS)
    with (
        patch(
            "cveta2.commands.labels.CvatClient",
            return_value=mock_client,
        ),
        patch(
            "cveta2.commands._helpers.load_projects_cache",
            return_value=[],
        ),
    ):
        app = CliApp()
        app.run(["labels", "--project", "1", "--list"])

    mock_client.get_project_labels.assert_called_once_with(1)


def test_cli_labels_list_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx(labels=[])
    with (
        patch(
            "cveta2.commands.labels.CvatClient",
            return_value=mock_client,
        ),
        patch(
            "cveta2.commands._helpers.load_projects_cache",
            return_value=[],
        ),
    ):
        app = CliApp()
        app.run(["labels", "--project", "1", "--list"])

    mock_client.get_project_labels.assert_called_once()


def test_cli_labels_noninteractive_without_list_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-interactive mode without --list should fail."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx(labels=_LABELS)
    with (
        patch(
            "cveta2.commands.labels.CvatClient",
            return_value=mock_client,
        ),
        patch(
            "cveta2.commands._helpers.load_projects_cache",
            return_value=[],
        ),
    ):
        app = CliApp()
        with pytest.raises(InteractiveModeRequiredError):
            app.run(["labels", "--project", "1"])


# ---------------------------------------------------------------------------
# Interactive add
# ---------------------------------------------------------------------------


def test_add_new_label() -> None:
    mock_client = MagicMock()
    updated = [*_LABELS, LabelInfo(id=4, name="fish", attributes=[])]
    mock_client.get_project_labels.return_value = updated

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.text.return_value.ask.return_value = "fish"
        result = _interactive_add(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, add=["fish"])
    assert len(result) == 4


def test_add_empty_name_cancels() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.text.return_value.ask.return_value = ""
        result = _interactive_add(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_add_none_cancels() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.text.return_value.ask.return_value = None
        _interactive_add(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()


def test_add_duplicate_name_rejects() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.text.return_value.ask.return_value = "cat"
        result = _interactive_add(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_add_duplicate_case_insensitive() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.text.return_value.ask.return_value = "CAT"
        _interactive_add(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()


def test_add_strips_whitespace() -> None:
    mock_client = MagicMock()
    updated = [*_LABELS, LabelInfo(id=4, name="fish", attributes=[])]
    mock_client.get_project_labels.return_value = updated

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.text.return_value.ask.return_value = "  fish  "
        _interactive_add(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, add=["fish"])


# ---------------------------------------------------------------------------
# Interactive rename
# ---------------------------------------------------------------------------


def test_rename_label() -> None:
    mock_client = MagicMock()
    updated = [
        LabelInfo(id=1, name="kitty", attributes=[], color="#ff0000"),
        _LABELS[1],
        _LABELS[2],
    ]
    mock_client.get_project_labels.return_value = updated

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 1
        mock_q.text.return_value.ask.return_value = "kitty"
        result = _interactive_rename(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, rename={1: "kitty"})
    assert len(result) == 3


def test_rename_cancel_select() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = None
        result = _interactive_rename(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_rename_empty_name_cancels() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 1
        mock_q.text.return_value.ask.return_value = ""
        _interactive_rename(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()


def test_rename_same_name_noop() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 1
        mock_q.text.return_value.ask.return_value = "cat"
        _interactive_rename(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()


def test_rename_to_existing_name_rejects() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 1
        mock_q.text.return_value.ask.return_value = "dog"
        _interactive_rename(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()


def test_rename_to_existing_case_insensitive() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 1
        mock_q.text.return_value.ask.return_value = "DOG"
        _interactive_rename(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()


# ---------------------------------------------------------------------------
# Interactive delete
# ---------------------------------------------------------------------------


def test_delete_no_annotations_confirmed() -> None:
    """Delete label with 0 annotations, user confirms."""
    mock_client = MagicMock()
    mock_client.count_label_usage.return_value = {}
    remaining = [_LABELS[1], _LABELS[2]]
    mock_client.get_project_labels.return_value = remaining

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.checkbox.return_value.ask.return_value = [1]
        mock_q.confirm.return_value.ask.return_value = True
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, delete=[1])
    assert len(result) == 2


def test_delete_no_annotations_declined() -> None:
    """Delete label with 0 annotations, user declines."""
    mock_client = MagicMock()
    mock_client.count_label_usage.return_value = {}

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.checkbox.return_value.ask.return_value = [1]
        mock_q.confirm.return_value.ask.return_value = False
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_delete_with_annotations_correct_confirmation() -> None:
    """Delete label that has annotations, user types correct name."""
    mock_client = MagicMock()
    mock_client.count_label_usage.return_value = {1: 42}
    remaining = [_LABELS[1], _LABELS[2]]
    mock_client.get_project_labels.return_value = remaining

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.checkbox.return_value.ask.return_value = [1]
        mock_q.text.return_value.ask.return_value = "cat"
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, delete=[1])
    assert len(result) == 2


def test_delete_with_annotations_wrong_confirmation() -> None:
    """Delete label that has annotations, user types wrong name."""
    mock_client = MagicMock()
    mock_client.count_label_usage.return_value = {1: 42}

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.checkbox.return_value.ask.return_value = [1]
        mock_q.text.return_value.ask.return_value = "wrong_name"
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_delete_with_annotations_none_confirmation() -> None:
    """Delete label that has annotations, user cancels (None)."""
    mock_client = MagicMock()
    mock_client.count_label_usage.return_value = {1: 10}

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.checkbox.return_value.ask.return_value = [1]
        mock_q.text.return_value.ask.return_value = None
        _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()


def test_delete_multiple_labels_with_annotations() -> None:
    """Delete two labels with annotations, confirm both names."""
    mock_client = MagicMock()
    mock_client.count_label_usage.return_value = {1: 10, 2: 5}
    remaining = [_LABELS[2]]
    mock_client.get_project_labels.return_value = remaining

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.checkbox.return_value.ask.return_value = [1, 2]
        mock_q.text.return_value.ask.return_value = "cat, dog"
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, delete=[1, 2])
    assert len(result) == 1


def test_delete_empty_selection_cancels() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.checkbox.return_value.ask.return_value = []
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.count_label_usage.assert_not_called()
    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_delete_none_selection_cancels() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.checkbox.return_value.ask.return_value = None
        _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.count_label_usage.assert_not_called()


def test_delete_label_no_annotations_among_annotated() -> None:
    """Select a label with 0 annotations while other labels have annotations.

    The selected label (id=1) has no annotations, so the simple confirm
    path is used, not the name-typing safety gate.
    """
    mock_client = MagicMock()
    mock_client.count_label_usage.return_value = {2: 100}
    remaining = [_LABELS[1], _LABELS[2]]
    mock_client.get_project_labels.return_value = remaining

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.checkbox.return_value.ask.return_value = [1]
        mock_q.confirm.return_value.ask.return_value = True
        _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, delete=[1])


# ---------------------------------------------------------------------------
# Hex color validation
# ---------------------------------------------------------------------------


def test_validate_hex_color_valid() -> None:
    assert _validate_hex_color("#ff0000") is True
    assert _validate_hex_color("#00FF00") is True
    assert _validate_hex_color("#123abc") is True


def test_validate_hex_color_invalid() -> None:
    assert isinstance(_validate_hex_color("ff0000"), str)
    assert isinstance(_validate_hex_color("#fff"), str)
    assert isinstance(_validate_hex_color("#gggggg"), str)
    assert isinstance(_validate_hex_color("red"), str)
    assert isinstance(_validate_hex_color(""), str)


# ---------------------------------------------------------------------------
# Interactive recolor
# ---------------------------------------------------------------------------


def test_recolor_label() -> None:
    mock_client = MagicMock()
    updated = [
        LabelInfo(id=1, name="cat", attributes=[], color="#0000ff"),
        _LABELS[1],
        _LABELS[2],
    ]
    mock_client.get_project_labels.return_value = updated

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 1
        mock_q.text.return_value.ask.return_value = "#0000ff"
        result = _interactive_recolor(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, recolor={1: "#0000ff"})
    assert len(result) == 3


def test_recolor_cancel_select() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = None
        result = _interactive_recolor(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_recolor_empty_cancels() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 1
        mock_q.text.return_value.ask.return_value = ""
        result = _interactive_recolor(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_recolor_none_cancels() -> None:
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 1
        mock_q.text.return_value.ask.return_value = None
        _interactive_recolor(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()


def test_recolor_same_color_noop() -> None:
    """Entering the same color (case-insensitive) does nothing."""
    mock_client = MagicMock()

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 1
        mock_q.text.return_value.ask.return_value = "#FF0000"
        _interactive_recolor(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()


def test_recolor_label_without_color() -> None:
    """Recolor a label that has no color set."""
    labels = [LabelInfo(id=10, name="fish", attributes=[], color="")]
    mock_client = MagicMock()
    updated = [LabelInfo(id=10, name="fish", attributes=[], color="#abcdef")]
    mock_client.get_project_labels.return_value = updated

    with patch("cveta2.commands.labels.questionary") as mock_q:
        mock_q.select.return_value.ask.return_value = 10
        mock_q.text.return_value.ask.return_value = "#abcdef"
        result = _interactive_recolor(mock_client, 1, labels)

    mock_client.update_project_labels.assert_called_once_with(
        1, recolor={10: "#abcdef"}
    )
    assert len(result) == 1


# ---------------------------------------------------------------------------
# CvatClient.update_project_labels — recolor
# ---------------------------------------------------------------------------


def test_update_labels_recolor_calls_partial_update() -> None:
    client = CvatClient(_CFG)
    mock_sdk = _setup_sdk_mock(client)

    client.update_project_labels(42, recolor={1: "#00ff00"})
    mock_sdk.api_client.projects_api.partial_update.assert_called_once()

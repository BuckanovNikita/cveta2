"""Tests for the ``cveta2 labels`` command and related client methods."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from cveta2._client.dtos import (
    LabelPatch,
    RawAnnotations,
    RawDataMeta,
    RawFrame,
)
from cveta2._client.ports import CvatApiPort
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
from cveta2.models import LabelAttributeInfo, LabelInfo, ProjectInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.helpers import (
    build_fake,
    client_with_api,
    make_fake_client,
    make_raw_shape,
    make_task,
    mock_client_ctx,
    patch_cli_client,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


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


def _cli_client(labels: list[LabelInfo] | None = None) -> MagicMock:
    """Mock CvatClient context manager for CLI-level labels tests."""
    client = mock_client_ctx()
    client.get_project_labels.return_value = labels or []
    client.count_label_usage.return_value = {}
    return client


def _client_with_api_mock() -> tuple[CvatClient, MagicMock]:
    """Build a CvatClient over a mocked API port for update_project_labels tests."""
    api = MagicMock(spec=CvatApiPort)
    return client_with_api(api), api


@contextmanager
def _patch_prompts(**returns: object) -> Iterator[None]:
    """Patch ``cveta2.commands.labels.interactive.<name>`` to fixed return values."""
    with pytest.MonkeyPatch.context() as mp:
        for name, value in returns.items():
            mp.setattr(
                f"cveta2.commands.labels.interactive.{name}",
                lambda *_a, _v=value, **_kw: _v,
            )
        yield


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


def test_format_label_joins_sections_with_a_double_space() -> None:
    """The rendered line is asserted whole, separators included.

    Every other format_display test uses substring checks, which say nothing
    about what glues the sections together — the string a user actually reads
    in the label picker.
    """
    label = LabelInfo(
        id=7,
        name="cat",
        color="#ff0000",
        attributes=[LabelAttributeInfo(id=10, name="breed")],
    )
    assert label.format_display() == "'cat' (id=7)  цвет=#ff0000  атрибуты: breed"


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
    normal_fake: LoadedFixtures,
) -> None:
    fake = normal_fake
    client = make_fake_client(fake)
    labels = client.get_project_labels(fake.project.id)
    assert len(labels) == len(fake.labels)
    label_names = {lbl.name for lbl in labels}
    expected_names = {lbl.name for lbl in fake.labels}
    assert label_names == expected_names


# ---------------------------------------------------------------------------
# CvatClient.count_label_usage (via FakeCvatApi)
# ---------------------------------------------------------------------------


def test_count_label_usage_shapes_per_label(
    normal_fake: LoadedFixtures,
) -> None:
    """Normal task has shapes; count_label_usage aggregates them."""
    fake = normal_fake
    client = make_fake_client(fake)
    counts = client.count_label_usage(fake.project.id)
    total = sum(counts.values())
    assert total == 30


def test_count_label_usage_empty_task(
    coco8_fixtures: LoadedFixtures,
) -> None:
    fake = build_fake(coco8_fixtures, ["all-empty"], statuses=["completed"])
    client = make_fake_client(fake)
    counts = client.count_label_usage(fake.project.id)
    assert sum(counts.values()) == 0


def test_count_label_usage_multiple_tasks(
    coco8_fixtures: LoadedFixtures,
) -> None:
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-bboxes-moved"],
        statuses=["completed", "completed"],
    )
    client = make_fake_client(fake)
    counts = client.count_label_usage(fake.project.id)
    total = sum(counts.values())
    assert total > 30


def test_count_label_usage_ids_match_labels(
    normal_fake: LoadedFixtures,
) -> None:
    """All label_ids in usage come from the project's labels."""
    fake = normal_fake
    client = make_fake_client(fake)
    counts = client.count_label_usage(fake.project.id)
    label_ids = {lbl.id for lbl in fake.labels}
    for lid in counts:
        assert lid in label_ids


def test_count_label_usage_deleted_frames_counted(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """Shapes on deleted frames are still counted (they exist in CVAT)."""
    fake = build_fake(coco8_fixtures, ["all-removed"], statuses=["completed"])
    client = make_fake_client(fake)
    counts = client.count_label_usage(fake.project.id)
    assert sum(counts.values()) == 30


# ---------------------------------------------------------------------------
# count_label_usage: per-label totals and the skipped-task branch
# ---------------------------------------------------------------------------

_USAGE_LABELS = [
    LabelInfo(id=1, name="cat", attributes=[]),
    LabelInfo(id=2, name="dog", attributes=[]),
]


def _usage_fixtures() -> LoadedFixtures:
    """Two tasks: task 10 has one cat and one dog, task 11 has two dogs."""
    data_meta = RawDataMeta(frames=[RawFrame(name="a.jpg", width=64, height=64)])
    return LoadedFixtures(
        project=ProjectInfo(id=1, name="usage"),
        tasks=[make_task(10), make_task(11)],
        labels=_USAGE_LABELS,
        task_data={
            10: (
                data_meta,
                RawAnnotations(
                    shapes=[
                        make_raw_shape(id=1, label_id=1),
                        make_raw_shape(id=2, label_id=2),
                    ],
                ),
            ),
            11: (
                data_meta,
                RawAnnotations(
                    shapes=[
                        make_raw_shape(id=3, label_id=2),
                        make_raw_shape(id=4, label_id=2),
                    ],
                ),
            ),
        },
    )


def test_count_label_usage_counts_each_label_separately() -> None:
    """The whole mapping is asserted, not ``sum(counts.values())``.

    Every other usage test collapses the result to a total, so any
    accounting error that preserves the total -- a per-label tally that
    starts at one, or attributing a shape to the wrong label -- was
    invisible.  The count drives a destructive label deletion.
    """
    client = CvatClient(CvatConfig(), api=FakeCvatApi(_usage_fixtures()))

    assert client.count_label_usage(1) == {1: 1, 2: 3}


def test_count_label_usage_continues_past_a_failing_task(
    capture_logs: list[str],
) -> None:
    """The ``except CvatApiError`` branch was never executed by any test.

    With the first of two tasks failing, the loop must skip it and keep
    counting: aborting instead would silently under-report usage before a
    label deletion, and the skipped-task summary is the only signal the
    user gets that the count is partial.
    """
    api = FakeCvatApi(
        _usage_fixtures(),
        fail_task_ids={10},
        fail_methods=("get_task_annotations",),
    )

    counts = CvatClient(CvatConfig(), api=api).count_label_usage(1)

    assert counts == {2: 2}
    assert any(
        "Пропущено задач при подсчёте меток: [10]" in message
        for message in capture_logs
    )


# ---------------------------------------------------------------------------
# CvatClient.update_project_labels (mock SDK)
# ---------------------------------------------------------------------------


def test_update_labels_no_ops_does_nothing() -> None:
    """Empty add/rename/delete does not call the API."""
    client, api = _client_with_api_mock()

    client.update_project_labels(1)
    api.patch_project_labels.assert_not_called()


@pytest.mark.parametrize(
    ("kwargs", "expected_patches"),
    [
        pytest.param(
            {"add": ["new_label"]},
            [LabelPatch(name="new_label")],
            id="add",
        ),
        pytest.param(
            {"delete": [1, 2]},
            [LabelPatch(id=1, deleted=True), LabelPatch(id=2, deleted=True)],
            id="delete",
        ),
        pytest.param(
            {"rename": {1: "renamed"}},
            [LabelPatch(id=1, name="renamed")],
            id="rename",
        ),
        pytest.param(
            {"recolor": {1: "#00ff00"}},
            [LabelPatch(id=1, color="#00ff00")],
            id="recolor",
        ),
    ],
)
def test_update_labels_calls_patch(
    kwargs: dict[str, Any],
    expected_patches: list[LabelPatch],
) -> None:
    client, api = _client_with_api_mock()

    client.update_project_labels(42, **kwargs)
    api.patch_project_labels.assert_called_once_with(42, expected_patches)


def test_update_labels_combines_patches_in_declaration_order() -> None:
    """Additions, renames, deletions and recolors go out as one ordered PATCH.

    Every case above passes exactly one kind of change, so nothing pinned
    either the order of the four blocks or the fact that they accumulate into
    a single call.
    """
    client, api = _client_with_api_mock()

    client.update_project_labels(
        42,
        add=["fish"],
        rename={1: "kitty"},
        delete=[2],
        recolor={3: "#00ff00"},
    )

    api.patch_project_labels.assert_called_once_with(
        42,
        [
            LabelPatch(name="fish"),
            LabelPatch(id=1, name="kitty"),
            LabelPatch(id=2, deleted=True),
            LabelPatch(id=3, color="#00ff00"),
        ],
    )


def test_update_labels_requires_context_manager() -> None:
    client = CvatClient(_CFG)
    with pytest.raises(RuntimeError, match="context manager"):
        client.update_project_labels(1, add=["x"])


# ---------------------------------------------------------------------------
# Labels CLI (--list, non-interactive)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("test_config")
@pytest.mark.parametrize("labels", [_LABELS, []], ids=["with-labels", "empty"])
def test_cli_labels_list(labels: list[LabelInfo]) -> None:
    mock_client = _cli_client(labels=labels)
    with patch_cli_client(mock_client):
        CliApp().run(["labels", "--project", "1", "--list"])

    mock_client.get_project_labels.assert_called_once_with(1)


@pytest.mark.usefixtures("test_config")
def test_cli_labels_noninteractive_without_list_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-interactive mode without --list should fail.

    The command raises ``InteractiveModeRequiredError``; the CLI dispatch
    boundary turns it into a clean ``sys.exit``.
    """
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")

    with (
        patch_cli_client(_cli_client(labels=_LABELS)),
        pytest.raises(SystemExit),
    ):
        CliApp().run(["labels", "--project", "1"])


# ---------------------------------------------------------------------------
# Interactive add
# ---------------------------------------------------------------------------


def test_add_new_label() -> None:
    mock_client = MagicMock()
    mock_client.get_project_labels.return_value = [
        *_LABELS,
        LabelInfo(id=4, name="fish", attributes=[]),
    ]

    with _patch_prompts(text="fish"):
        result = _interactive_add(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, add=["fish"])
    assert len(result) == 4


@pytest.mark.parametrize("name", ["", None, "cat", "CAT"])
def test_add_rejected_name_no_update(name: str | None) -> None:
    """Empty/None cancels and duplicate (case-insensitive) names are rejected."""
    mock_client = MagicMock()

    with _patch_prompts(text=name):
        result = _interactive_add(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


# ---------------------------------------------------------------------------
# Interactive rename
# ---------------------------------------------------------------------------


def test_rename_label() -> None:
    mock_client = MagicMock()
    mock_client.get_project_labels.return_value = [
        LabelInfo(id=1, name="kitty", attributes=[], color="#ff0000"),
        _LABELS[1],
        _LABELS[2],
    ]

    with _patch_prompts(select_label=1, text="kitty"):
        result = _interactive_rename(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, rename={1: "kitty"})
    assert len(result) == 3


@pytest.mark.parametrize(
    ("select", "text"),
    [
        (None, None),  # cancel at label selection
        (1, None),  # empty new name
        (1, "cat"),  # same name (noop)
        (1, "dog"),  # existing name
        (1, "DOG"),  # existing name, case-insensitive
    ],
    ids=["cancel-select", "empty-name", "same-name", "existing", "existing-ci"],
)
def test_rename_no_update(select: int | None, text: str | None) -> None:
    """Selection cancel, empty/same/duplicate names all skip the API call."""
    mock_client = MagicMock()

    with _patch_prompts(select_label=select, text=text):
        result = _interactive_rename(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


# ---------------------------------------------------------------------------
# Interactive delete
# ---------------------------------------------------------------------------


def _delete_client(usage: dict[int, int], remaining: list[LabelInfo]) -> MagicMock:
    mock_client = MagicMock()
    mock_client.count_label_usage.return_value = usage
    mock_client.get_project_labels.return_value = remaining
    return mock_client


@pytest.mark.parametrize(
    ("usage", "selection", "prompts"),
    [
        ({}, [1], {"confirm": True}),  # 0 annotations, confirm
        ({1: 42}, [1], {"text": "cat"}),  # annotated, correct name typed
        ({2: 100}, [1], {"confirm": True}),  # selected label unannotated → confirm
    ],
    ids=[
        "no-annotations-confirm",
        "annotated-name-typed",
        "unannotated-among-annotated",
    ],
)
def test_delete_single_label_proceeds(
    usage: dict[int, int],
    selection: list[int],
    prompts: dict[str, object],
) -> None:
    """A confirmed single-label delete calls the API and drops the label."""
    mock_client = _delete_client(usage, [_LABELS[1], _LABELS[2]])

    with _patch_prompts(select_labels=selection, **prompts):
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, delete=[1])
    assert len(result) == 2


@pytest.mark.parametrize(
    ("usage", "prompts"),
    [
        ({}, {"confirm": False}),  # 0 annotations, declined
        ({1: 42}, {"text": "wrong_name"}),  # annotated, wrong name typed
        ({1: 10}, {"text": None}),  # annotated, cancelled (None)
    ],
    ids=["declined", "wrong-name", "cancelled"],
)
def test_delete_no_update(usage: dict[int, int], prompts: dict[str, object]) -> None:
    """Decline / wrong-name / cancel all skip the API call."""
    mock_client = MagicMock()
    mock_client.count_label_usage.return_value = usage

    with _patch_prompts(select_labels=[1], **prompts):
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_delete_multiple_labels_with_annotations() -> None:
    """Delete two labels with annotations, confirm both names."""
    mock_client = _delete_client({1: 10, 2: 5}, [_LABELS[2]])

    with _patch_prompts(select_labels=[1, 2], text="cat, dog"):
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, delete=[1, 2])
    assert len(result) == 1


@pytest.mark.parametrize("selection", [[], None])
def test_delete_empty_selection_cancels(selection: list[int] | None) -> None:
    """Empty or None checkbox selection cancels before any usage lookup."""
    mock_client = MagicMock()

    with _patch_prompts(select_labels=selection or []):
        result = _interactive_delete(mock_client, 1, list(_LABELS))

    mock_client.count_label_usage.assert_not_called()
    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


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
    mock_client.get_project_labels.return_value = [
        LabelInfo(id=1, name="cat", attributes=[], color="#0000ff"),
        _LABELS[1],
        _LABELS[2],
    ]

    with _patch_prompts(select_label=1, text="#0000ff"):
        result = _interactive_recolor(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_called_once_with(1, recolor={1: "#0000ff"})
    assert len(result) == 3


@pytest.mark.parametrize(
    ("select", "color"),
    [
        (None, None),  # cancel at label selection
        (1, ""),  # empty color
        (1, None),  # None color
        (1, "#FF0000"),  # same color (case-insensitive noop)
    ],
    ids=["cancel-select", "empty", "none", "same-color"],
)
def test_recolor_no_update(select: int | None, color: str | None) -> None:
    """Selection cancel, empty/None/same color all skip the API call."""
    mock_client = MagicMock()

    with _patch_prompts(select_label=select, text=color):
        result = _interactive_recolor(mock_client, 1, list(_LABELS))

    mock_client.update_project_labels.assert_not_called()
    assert result == list(_LABELS)


def test_recolor_label_without_color() -> None:
    """Recolor a label that has no color set."""
    labels = [LabelInfo(id=10, name="fish", attributes=[], color="")]
    mock_client = MagicMock()
    mock_client.get_project_labels.return_value = [
        LabelInfo(id=10, name="fish", attributes=[], color="#abcdef")
    ]

    with _patch_prompts(select_label=10, text="#abcdef"):
        result = _interactive_recolor(mock_client, 1, labels)

    mock_client.update_project_labels.assert_called_once_with(
        1, recolor={10: "#abcdef"}
    )
    assert len(result) == 1

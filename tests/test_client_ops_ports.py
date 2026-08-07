"""Contract tests for the ``_client_ops`` read/fetch mixins over the port.

Two contracts that every mixin method shares and that no scenario test
pins, because a fake API accepts whatever it is handed:

* the ``RuntimeError`` raised without an open context names the operation
  the caller asked for;
* the project id the caller passes is the project id the port receives.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from cveta2._client.ports import CvatApiPort
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from tests.helpers import client_with_api

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# _require_api: the RuntimeError names the operation
# ---------------------------------------------------------------------------

_CONTEXT_REQUIRED_OPS: list[tuple[str, Callable[[CvatClient], object]]] = [
    ("list_organizations", lambda c: c.list_organizations()),
    ("list_projects", lambda c: c.list_projects()),
    ("list_project_tasks", lambda c: c.list_project_tasks(1)),
    ("get_task", lambda c: c.get_task(1)),
    ("get_project_labels", lambda c: c.get_project_labels(1)),
    ("count_label_usage", lambda c: c.count_label_usage(1)),
    ("detect_project_cloud_storage", lambda c: c.detect_project_cloud_storage(1)),
    ("prepare_fetch", lambda c: c.prepare_fetch(1)),
]


@pytest.mark.parametrize(
    ("operation", "call"),
    _CONTEXT_REQUIRED_OPS,
    ids=[name for name, _ in _CONTEXT_REQUIRED_OPS],
)
def test_operation_outside_context_manager_names_itself(
    operation: str,
    call: Callable[[CvatClient], object],
) -> None:
    """The literal each method hands ``_require_api`` must be its own name.

    Every mixin method passes a hand-written string that only ever reaches
    this error message, so nothing distinguished ``"get_task"`` from
    ``None``, ``"XXget_taskXX"`` or ``"GET_TASK"`` -- the user would be
    told to wrap the wrong call in a context manager.
    """
    client = CvatClient(CvatConfig())

    expected = re.escape(f"{operation}() requires a context manager")
    with pytest.raises(RuntimeError, match=expected):
        call(client)


# ---------------------------------------------------------------------------
# Project-id forwarding
# ---------------------------------------------------------------------------


def _mock_port() -> MagicMock:
    """Build a port mock whose list-returning methods yield empty lists."""
    api = MagicMock(spec=CvatApiPort)
    api.get_project_tasks.return_value = []
    api.get_project_labels.return_value = []
    return api


def test_list_project_tasks_forwards_project_id() -> None:
    """``get_project_tasks(None)`` is invisible to a fake that ignores the id."""
    api = _mock_port()

    client_with_api(api).list_project_tasks(17)

    api.get_project_tasks.assert_called_once_with(17)


def test_list_tasks_completed_after_forwards_project_id() -> None:
    """The cutoff filter runs the same over any project's tasks."""
    api = _mock_port()

    client_with_api(api).list_tasks_completed_after(23, "2026-01-01T00:00:00+00:00")

    api.get_project_tasks.assert_called_once_with(23)


def test_get_project_labels_forwards_project_id() -> None:
    """Fixture fakes serve one label set regardless of the id they are given."""
    api = _mock_port()

    client_with_api(api).get_project_labels(31)

    api.get_project_labels.assert_called_once_with(31)


def test_count_label_usage_forwards_project_id() -> None:
    """An empty task list yields ``{}`` for every project id, right or wrong."""
    api = _mock_port()

    assert client_with_api(api).count_label_usage(41) == {}

    api.get_project_tasks.assert_called_once_with(41)


def test_detect_project_cloud_storage_forwards_project_id() -> None:
    """The fake returns ``None`` for every project, so the id was unpinned."""
    api = _mock_port()

    client_with_api(api).detect_project_cloud_storage(53)

    api.get_project_cloud_storage.assert_called_once_with(53)


def test_prepare_fetch_forwards_project_id_to_both_reads() -> None:
    """Tasks and labels must be read for the *requested* project.

    ``prepare_fetch`` hands the id down two levels (to ``_prepare_fetch``,
    then to each port call); a single-project fake cannot tell the right
    id from ``None``.
    """
    api = _mock_port()

    client_with_api(api).prepare_fetch(67)

    api.get_project_tasks.assert_called_once_with(67)
    api.get_project_labels.assert_called_once_with(67)

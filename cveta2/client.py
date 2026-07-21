"""CVAT client logic: connect, fetch annotations, orchestrate task operations.

All CVAT SDK interaction goes through :class:`CvatApiPort`
(``cveta2._client``); this module holds only domain orchestration.

The behaviour is split across cohesive mixins in :mod:`cveta2._client_ops`
(same architecture layer as this module); :class:`CvatClient` composes them.
Internal helpers live in :mod:`cveta2._client_ops` — import them from there.
"""

from __future__ import annotations

from cveta2._client_ops.base import _ClientBase
from cveta2._client_ops.fetch import _FetchMixin
from cveta2._client_ops.images import _ImageMixin
from cveta2._client_ops.read import _ReadMixin
from cveta2._client_ops.session import TaskWriteSession
from cveta2._client_ops.shared import FetchContext
from cveta2._client_ops.task_ops import _TaskOpsMixin
from cveta2._client_ops.write import _WriteMixin

__all__ = [
    "CvatClient",
    "FetchContext",
    "TaskWriteSession",
]


class CvatClient(
    _FetchMixin,
    _ImageMixin,
    _WriteMixin,
    _TaskOpsMixin,
    _ReadMixin,
    _ClientBase,
):
    """High-level CVAT client that fetches bbox annotations.

    Can be used as a context manager to keep the SDK connection open
    across multiple calls::

        with CvatClient(cfg) as client:
            projects = client.list_projects()
            ctx = client.prepare_fetch(project_id)

    The context manager is required for all remote calls unless an
    ``api`` port is injected (tests).
    """

"""CVAT client logic: connect, fetch annotations, orchestrate task operations.

All CVAT SDK interaction goes through :class:`CvatApiPort`
(``cveta2._client``); this module holds only domain orchestration.

The behaviour is split across cohesive mixins in :mod:`cveta2._client_ops`
(same architecture layer as this module); :class:`CvatClient` composes them.
The value objects, constants and free helpers below are re-exported here so
existing ``from cveta2.client import ...`` call sites keep working.
"""

from __future__ import annotations

from cveta2._client_ops.base import _ClientBase
from cveta2._client_ops.fetch import _FetchMixin, _filter_tasks_for_fetch
from cveta2._client_ops.images import _ImageMixin
from cveta2._client_ops.read import _ReadMixin
from cveta2._client_ops.shared import (
    _HTTP_5XX_MAX,
    _HTTP_5XX_MIN,
    FetchContext,
    _FetchAnnotationsOptions,
    _log_task_5xx_skip,
)
from cveta2._client_ops.task_ops import _TaskOpsMixin
from cveta2._client_ops.write import (
    _log_issue_skips,
    _select_new_issue_rows,
    _WriteMixin,
)

__all__ = [
    "_HTTP_5XX_MAX",
    "_HTTP_5XX_MIN",
    "CvatClient",
    "FetchContext",
    "_FetchAnnotationsOptions",
    "_filter_tasks_for_fetch",
    "_log_issue_skips",
    "_log_task_5xx_skip",
    "_select_new_issue_rows",
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

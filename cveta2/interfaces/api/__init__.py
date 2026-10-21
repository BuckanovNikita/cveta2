"""Public workflow API: module-level functions mirroring the data CLI commands.

Every data command (fetch, upload, convert, merge, labels, task ops,
whats-new, ignore, s3-sync) has a counterpart here; the interactive-only
commands (``setup``, ``setup-cache``, ``doctor``) do not.

Every remote function accepts an optional ``connection=`` argument (a
:class:`Connection`); when omitted or partially filled, configuration is
resolved from environment variables, ``~/.config/cveta2/config.yaml``
and the built-in preset.  The API never prompts — missing settings raise
:class:`MissingHostError` / :class:`MissingCredentialsError`.

The ``PLR0913`` suppressions in these modules are deliberate and are
explained here once rather than at each site: these are the public
library signatures, and every argument is an explicit keyword a caller
names.  Collapsing them into option objects would move the width into a
type the caller has to import first, and would be a breaking change for
anyone already calling them.  Internal layers do use option objects —
see :class:`~cveta2.application.use_cases.fetch.FetchTarget`.
"""

from cveta2.composition.conversion import (
    convert_from_yolo,
    convert_to_coco,
    convert_to_yolo,
)
from cveta2.interfaces.api.fetch import fetch, fetch_task
from cveta2.interfaces.api.projects import (
    get_labels,
    ignore,
    merge,
    s3_sync,
    update_labels,
    whats_new,
)
from cveta2.interfaces.api.task_ops import (
    task_delete,
    task_drop_label,
    task_mark_deleted,
    task_set_status,
)
from cveta2.interfaces.api.types import CacheMode as CacheMode
from cveta2.interfaces.api.types import Connection, UploadResult, WhatsNewResult
from cveta2.interfaces.api.upload import upload

__all__ = [
    "Connection",
    "UploadResult",
    "WhatsNewResult",
    "convert_from_yolo",
    "convert_to_coco",
    "convert_to_yolo",
    "fetch",
    "fetch_task",
    "get_labels",
    "ignore",
    "merge",
    "s3_sync",
    "task_delete",
    "task_drop_label",
    "task_mark_deleted",
    "task_set_status",
    "update_labels",
    "upload",
    "whats_new",
]

# Preserve established pickle paths and callable metadata across internal moves.
for _export in (
    Connection,
    UploadResult,
    WhatsNewResult,
    fetch,
    fetch_task,
    get_labels,
    ignore,
    merge,
    s3_sync,
    task_delete,
    task_drop_label,
    task_mark_deleted,
    task_set_status,
    update_labels,
    upload,
    whats_new,
):
    _export.__module__ = __name__
del _export

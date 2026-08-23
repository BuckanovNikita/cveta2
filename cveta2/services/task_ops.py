"""Task-mutation scaffolding shared by the CLI and the public API.

The local cache entry is invalidated on exit even when the mutation
fails or the user declines a confirmation — conservative but safe. It
lives here so the CLI and the api layer cannot drift on the one step
that keeps a stale entry from surviving a later mutation.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from cveta2.task_cache import invalidate_local_entry

if TYPE_CHECKING:
    from collections.abc import Iterator

    from cveta2.client import CvatClient
    from cveta2.models import TaskInfo


@contextmanager
def resolved_task(
    client: CvatClient,
    project_id: int,
    project_name: str,
    task: int | str,
) -> Iterator[TaskInfo]:
    """Resolve *task* and invalidate its cache entry when the block exits.

    The project is already resolved by the caller: the CLI resolves it
    through a prompt, the api layer without one, and services may not
    import the interactive layer.
    """
    tasks = client.list_project_tasks(project_id)
    task_info = client.resolve_task_selectors(tasks, [task])[0]
    try:
        yield task_info
    finally:
        invalidate_local_entry(project_id, task_info.id, project_name)

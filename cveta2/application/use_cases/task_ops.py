"""Task-mutation scaffolding shared by the CLI and the public API.

The task's cache entry — local and in the S3 mirror — is invalidated
on exit even when the mutation fails or the user declines a
confirmation — conservative but safe. It lives here so the CLI and the
api layer cannot drift on the one step that keeps a stale entry from
surviving a later mutation.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from cveta2.application.client import ApplicationClient as CvatClient
from cveta2.application.ports.cache import CacheInvalidator
from cveta2.domain.models import TaskInfo


@contextmanager
def resolved_task(
    client: CvatClient,
    project_id: int,
    project_name: str,
    task: int | str,
    *,
    invalidate: CacheInvalidator,
) -> Iterator[TaskInfo]:
    """Resolve *task* and invalidate its cache entry when the block exits.

    The project is already resolved by the caller: the CLI resolves it
    through a prompt, the api layer without one, and services may not
    import the interactive layer.  The project's cloud storage is looked
    up before the block runs, so nothing that talks to CVAT sits in the
    ``finally`` where it could mask the mutation's own error.
    """
    tasks = client.list_project_tasks(project_id)
    task_info = client.resolve_task_selectors(tasks, [task])[0]
    cs_info = client.detect_project_cloud_storage(project_id)
    try:
        yield task_info
    finally:
        invalidate(project_id, task_info.id, project_name, cs_info)

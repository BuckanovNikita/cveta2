"""Protocols defining the CVAT API boundary.

``CvatApiPort`` is the single seam between business logic and the CVAT SDK.
In production it is satisfied by ``SdkCvatApiAdapter``; in tests a fake
returning fixture data (or a ``MagicMock(spec=CvatApiPort)``) is used
instead.  Implementations raise :class:`cveta2.exceptions.CvatApiError`
for API-level failures — no ``cvat_sdk`` exception types cross this
boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from cveta2._client.dtos import (
        LabelPatch,
        NewIssue,
        NewShape,
        RawAnnotations,
        RawDataMeta,
        RawIssue,
        RawJob,
        RawShape,
        UploadTaskSpec,
    )
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import LabelInfo, OrganizationInfo, ProjectInfo, TaskInfo


class CvatApiPort(Protocol):
    """Full CVAT API surface used by ``CvatClient``."""

    def list_organizations(self) -> list[OrganizationInfo]:
        """Return all organizations the user is a member of."""
        ...

    def set_organization(self, org: str | None) -> None:
        """Scope subsequent requests to *org* (``None`` = personal workspace)."""
        ...

    def list_projects(self) -> list[ProjectInfo]:
        """Return all accessible projects."""
        ...

    def get_project(self, project_id: int) -> ProjectInfo:
        """Return one project by id."""
        ...

    def get_project_tasks(self, project_id: int) -> list[TaskInfo]:
        """Return tasks belonging to a project."""
        ...

    def get_task(self, task_id: int) -> TaskInfo:
        """Return one task by id (with its ``project_id``)."""
        ...

    def get_project_labels(self, project_id: int) -> list[LabelInfo]:
        """Return label definitions for a project."""
        ...

    def get_project_cloud_storage(self, project_id: int) -> CloudStorageInfo | None:
        """Return the project's source cloud storage, or None."""
        ...

    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        """Return frame metadata and deleted frame IDs for a task."""
        ...

    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        """Return shapes for a task."""
        ...

    def get_task_issues(self, task_id: int) -> list[RawIssue]:
        """Return review issues (with comment texts) for a task."""
        ...

    def get_task_labels(self, task_id: int) -> list[LabelInfo]:
        """Return label definitions available in a task."""
        ...

    def get_task_jobs(self, task_id: int) -> list[RawJob]:
        """Return jobs (with frame ranges) of a task."""
        ...

    def get_task_size(self, task_id: int) -> int:
        """Return the number of frames in a task."""
        ...

    def create_task(self, spec: UploadTaskSpec) -> int:
        """Create an empty task and return its id."""
        ...

    def attach_task_data(self, task_id: int, spec: UploadTaskSpec) -> None:
        """Attach cloud-storage files to a task and wait for processing."""
        ...

    def put_task_shapes(self, task_id: int, shapes: list[NewShape]) -> None:
        """Add annotation shapes to a task."""
        ...

    def create_issue(self, issue: NewIssue) -> None:
        """Open a review issue on a job frame."""
        ...

    def set_deleted_frames(self, task_id: int, frame_ids: list[int]) -> None:
        """Replace the task's deleted-frames list."""
        ...

    def delete_shapes(self, task_id: int, shapes: list[RawShape]) -> None:
        """Delete the given existing shapes from a task."""
        ...

    def delete_task(self, task_id: int) -> None:
        """Delete a task permanently."""
        ...

    def update_job(
        self,
        job_id: int,
        *,
        stage: str | None = None,
        state: str | None = None,
    ) -> None:
        """Patch stage and/or state of a job."""
        ...

    def patch_project_labels(
        self,
        project_id: int,
        patches: list[LabelPatch],
    ) -> None:
        """Apply label additions/renames/deletions/recolors to a project."""
        ...

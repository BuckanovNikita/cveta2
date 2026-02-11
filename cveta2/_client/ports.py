"""Protocol defining the CVAT API boundary.

``CvatApiPort`` is the single seam between business logic and the CVAT SDK.
In production it is satisfied by ``SdkCvatApiAdapter``; in tests a trivial
fake returning fixture data can be used instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from cveta2._client.dtos import (
        RawAnnotations,
        RawDataMeta,
        RawLabel,
        RawProject,
        RawTask,
    )


class CvatApiPort(Protocol):
    """Minimal interface for CVAT API operations used by ``CvatClient``."""

    def list_projects(self) -> list[RawProject]:
        """Return all accessible projects."""
        ...

    def get_project_tasks(self, project_id: int) -> list[RawTask]:
        """Return tasks belonging to a project."""
        ...

    def get_project_labels(self, project_id: int) -> list[RawLabel]:
        """Return label definitions for a project."""
        ...

    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        """Return frame metadata and deleted frame IDs for a task."""
        ...

    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        """Return shapes and tracks for a task."""
        ...

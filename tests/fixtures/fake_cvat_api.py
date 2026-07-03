"""Fake CvatApiPort implementation backed by loaded fixture data.

Used in integration tests to exercise ``CvatClient.fetch_annotations``
without the real CVAT SDK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cvat_sdk.api_client.exceptions import ApiException

from cveta2.models import ProjectInfo
from tests.fixtures.fake_cvat_project import LoadedFixtures

if TYPE_CHECKING:
    from collections.abc import Collection

    from cveta2._client.dtos import RawAnnotations, RawDataMeta, RawIssue
    from cveta2.models import LabelInfo, TaskInfo

_DEFAULT_FAIL_METHODS = ("get_task_data_meta", "get_task_annotations")


class FakeCvatApi:
    """``CvatApiPort`` implementation that returns pre-built fixture data.

    Satisfies the ``CvatApiPort`` protocol structurally (duck-typing).
    Task-scoped methods can be made to fail for selected task ids via
    *fail_task_ids* / *fail_status* / *fail_methods*; every call to
    ``get_task_annotations`` is recorded in ``annotation_calls``.
    """

    def __init__(
        self,
        fixtures: LoadedFixtures,
        *,
        fail_task_ids: Collection[int] = frozenset(),
        fail_status: int = 500,
        fail_methods: Collection[str] = _DEFAULT_FAIL_METHODS,
    ) -> None:
        """Unpack fixture data into internal stores."""
        self._project = fixtures.project
        self._tasks = fixtures.tasks
        self._labels = fixtures.labels
        self._task_data = fixtures.task_data
        self._issues = fixtures.issues or {}
        self._fail_task_ids = frozenset(fail_task_ids)
        self._fail_status = fail_status
        self._fail_methods = frozenset(fail_methods)
        self.annotation_calls: list[int] = []

    @classmethod
    def from_tasks(
        cls,
        tasks: list[TaskInfo],
        *,
        project_name: str = "fake",
    ) -> FakeCvatApi:
        """Create a fake API serving only a project with the given tasks."""
        fixtures = LoadedFixtures(
            project=ProjectInfo(id=1, name=project_name),
            tasks=tasks,
            labels=[],
            task_data={},
        )
        return cls(fixtures)

    def _raise_if_failing(self, method: str, task_id: int) -> None:
        if task_id in self._fail_task_ids and method in self._fail_methods:
            raise ApiException(status=self._fail_status, reason="fake failure")

    def list_projects(self) -> list[ProjectInfo]:
        """Return the single fixture project."""
        return [self._project]

    def get_project_tasks(self, _project_id: int) -> list[TaskInfo]:
        """Return tasks from fixture data."""
        return list(self._tasks)

    def get_project_labels(self, _project_id: int) -> list[LabelInfo]:
        """Return labels from fixture data."""
        return list(self._labels)

    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        """Return frame metadata for a task by id."""
        self._raise_if_failing("get_task_data_meta", task_id)
        data_meta, _annotations = self._task_data[task_id]
        return data_meta

    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        """Return shapes for a task by id."""
        self.annotation_calls.append(task_id)
        self._raise_if_failing("get_task_annotations", task_id)
        _data_meta, annotations = self._task_data[task_id]
        return annotations

    def get_task_issues(self, task_id: int) -> list[RawIssue]:
        """Return issues for a task by id (empty when not configured)."""
        self._raise_if_failing("get_task_issues", task_id)
        return list(self._issues.get(task_id, []))

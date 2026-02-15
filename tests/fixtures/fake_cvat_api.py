"""Fake CvatApiPort implementation backed by loaded fixture data.

Used in integration tests to exercise ``CvatClient.fetch_annotations``
without the real CVAT SDK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cveta2._client.dtos import (
        RawAnnotations,
        RawDataMeta,
        RawLabel,
        RawProject,
        RawTask,
    )
    from tests.fixtures.fake_cvat_project import LoadedFixtures


class FakeCvatApi:
    """``CvatApiPort`` implementation that returns pre-built fixture data.

    Satisfies the ``CvatApiPort`` protocol structurally (duck-typing).
    """

    def __init__(self, fixtures: LoadedFixtures) -> None:
        """Unpack fixture data into internal stores."""
        self._project = fixtures.project
        self._tasks = fixtures.tasks
        self._labels = fixtures.labels
        self._task_data = fixtures.task_data

    def list_projects(self) -> list[RawProject]:
        """Return the single fixture project."""
        return [self._project]

    def get_project_tasks(self, project_id: int) -> list[RawTask]:  # noqa: ARG002
        """Return tasks from fixture data."""
        return list(self._tasks)

    def get_project_labels(self, project_id: int) -> list[RawLabel]:  # noqa: ARG002
        """Return labels from fixture data."""
        return list(self._labels)

    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        """Return frame metadata for a task by id."""
        data_meta, _annotations = self._task_data[task_id]
        return data_meta

    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        """Return shapes and tracks for a task by id."""
        _data_meta, annotations = self._task_data[task_id]
        return annotations

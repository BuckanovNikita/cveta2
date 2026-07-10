"""Fake CvatApiPort implementation backed by loaded fixture data.

Used in tests to exercise the ``prepare_fetch`` / ``fetch_one_task``
pipeline without the real CVAT SDK.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cveta2._client.dtos import RawAnnotations, RawDataMeta, RawFrame
from cveta2.exceptions import CvatApiError
from cveta2.models import ProjectInfo, TaskInfo
from tests.fixtures.fake_cvat_project import LoadedFixtures

if TYPE_CHECKING:
    from collections.abc import Collection

    from cveta2._client.dtos import (
        LabelPatch,
        NewIssue,
        NewShape,
        RawIssue,
        RawJob,
        RawShape,
        UploadTaskSpec,
    )
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import LabelInfo

_DEFAULT_FAIL_METHODS = ("get_task_data_meta", "get_task_annotations")


@dataclass
class RecordedWrites:
    """Everything a test can assert about the fake's write traffic."""

    created_tasks: list[UploadTaskSpec] = field(default_factory=list)
    shapes: dict[int, list[NewShape]] = field(default_factory=dict)
    issues: list[NewIssue] = field(default_factory=list)
    deleted_frames: dict[int, list[int]] = field(default_factory=dict)
    deleted_shapes: dict[int, list[RawShape]] = field(default_factory=dict)
    deleted_tasks: list[int] = field(default_factory=list)
    job_updates: list[tuple[int, str | None, str | None]] = field(default_factory=list)
    label_patches: dict[int, list[LabelPatch]] = field(default_factory=dict)


class FakeCvatApi:
    """``CvatApiPort`` implementation that returns pre-built fixture data.

    Satisfies the ``CvatApiPort`` protocol structurally (duck-typing).
    Task-scoped methods can be made to fail for selected task ids via
    *fail_task_ids* / *fail_status* / *fail_methods*; every call to
    ``get_task_annotations`` is recorded in ``annotation_calls``.

    Write methods record their traffic on ``self.writes`` and keep the
    in-memory task store consistent (``create_task_with_data`` allocates
    an id and synthesizes frame metadata, ``set_deleted_frames`` updates
    the stored ``data_meta``), so full upload flows run against the fake.
    A ``MagicMock(spec=CvatApiPort)`` remains acceptable only for narrow
    single-method interaction tests (error injection, exact call-arg
    assertions where a one-line ``return_value`` beats fixture setup).
    """

    def __init__(
        self,
        fixtures: LoadedFixtures,
        *,
        fail_task_ids: Collection[int] = frozenset(),
        fail_status: int = 500,
        fail_methods: Collection[str] = _DEFAULT_FAIL_METHODS,
    ) -> None:
        """Unpack fixture data into internal stores (copies: writes stay local)."""
        self._project = fixtures.project
        self._tasks = list(fixtures.tasks)
        self._labels = fixtures.labels
        self._task_data = dict(fixtures.task_data)
        self._issues = fixtures.issues or {}
        self._fail_task_ids = frozenset(fail_task_ids)
        self._fail_status = fail_status
        self._fail_methods = frozenset(fail_methods)
        self.annotation_calls: list[int] = []
        self.writes = RecordedWrites()

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
            raise CvatApiError("fake failure", status_code=self._fail_status)

    # ------------------------------------------------------------------
    # Read port
    # ------------------------------------------------------------------

    def list_projects(self) -> list[ProjectInfo]:
        """Return the single fixture project."""
        return [self._project]

    def get_project_tasks(self, _project_id: int) -> list[TaskInfo]:
        """Return tasks from fixture data."""
        return list(self._tasks)

    def get_project_labels(self, _project_id: int) -> list[LabelInfo]:
        """Return labels from fixture data."""
        return list(self._labels)

    def get_project_cloud_storage(self, _project_id: int) -> CloudStorageInfo | None:
        """Return None: fixture projects have no cloud storage."""
        return None

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

    def get_task_labels(self, _task_id: int) -> list[LabelInfo]:
        """Return the project labels (fixtures share labels across tasks)."""
        return list(self._labels)

    def get_task_jobs(self, task_id: int) -> list[RawJob]:
        """Return a single job spanning all frames of the task."""
        from cveta2._client.dtos import RawJob

        data_meta, _annotations = self._task_data[task_id]
        return [RawJob(id=task_id, start_frame=0, stop_frame=len(data_meta.frames))]

    def get_task_size(self, task_id: int) -> int:
        """Return the number of frames in a task."""
        data_meta, _annotations = self._task_data[task_id]
        return len(data_meta.frames)

    # ------------------------------------------------------------------
    # Write port (records traffic; keeps the task store consistent)
    # ------------------------------------------------------------------

    def create_task_with_data(self, spec: UploadTaskSpec) -> int:
        """Allocate a task id and synthesize frame metadata from the spec."""
        self.writes.created_tasks.append(spec)
        task_id = max((t.id for t in self._tasks), default=0) + 1
        data_meta = RawDataMeta(
            frames=[RawFrame(name=f, width=640, height=480) for f in spec.server_files]
        )
        self._task_data[task_id] = (data_meta, RawAnnotations())
        self._tasks.append(
            TaskInfo(
                id=task_id,
                name=spec.name,
                status="annotation",
                subset="",
                updated_date="",
            )
        )
        return task_id

    def put_task_shapes(self, task_id: int, shapes: list[NewShape]) -> None:
        """Record uploaded shapes per task."""
        self.writes.shapes.setdefault(task_id, []).extend(shapes)

    def create_issue(self, issue: NewIssue) -> None:
        """Record a created issue."""
        self.writes.issues.append(issue)

    def set_deleted_frames(self, task_id: int, frame_ids: list[int]) -> None:
        """Record deleted frames and update the stored ``data_meta``."""
        self.writes.deleted_frames[task_id] = list(frame_ids)
        data_meta, annotations = self._task_data[task_id]
        self._task_data[task_id] = (
            dataclasses.replace(data_meta, deleted_frames=list(frame_ids)),
            annotations,
        )

    def delete_shapes(self, task_id: int, shapes: list[RawShape]) -> None:
        """Record deleted shapes per task."""
        self.writes.deleted_shapes.setdefault(task_id, []).extend(shapes)

    def delete_task(self, task_id: int) -> None:
        """Record the deletion and drop the task from the store."""
        self.writes.deleted_tasks.append(task_id)
        self._tasks = [t for t in self._tasks if t.id != task_id]
        self._task_data.pop(task_id, None)

    def update_job(
        self,
        job_id: int,
        *,
        stage: str | None = None,
        state: str | None = None,
    ) -> None:
        """Record a job stage/state update."""
        self.writes.job_updates.append((job_id, stage, state))

    def patch_project_labels(
        self,
        project_id: int,
        patches: list[LabelPatch],
    ) -> None:
        """Record label patches per project."""
        self.writes.label_patches.setdefault(project_id, []).extend(patches)

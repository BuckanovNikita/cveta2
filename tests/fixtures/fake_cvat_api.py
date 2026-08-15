"""Fake CvatApiPort implementation backed by loaded fixture data.

Used in tests to exercise the ``prepare_fetch`` / ``fetch_one_task``
pipeline without the real CVAT SDK.
"""

from __future__ import annotations

import dataclasses
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cveta2._client.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawIssue,
    RawShape,
)
from cveta2.exceptions import CvatApiError
from cveta2.models import OrganizationInfo, ProjectInfo, TaskInfo
from tests.fixtures.fake_cvat_project import LoadedFixtures

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from cveta2._client.dtos import (
        LabelPatch,
        NewIssue,
        NewShape,
        RawJob,
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


def _as_raw_shape(shape_id: int, shape: NewShape) -> RawShape:
    """Turn an uploaded shape into the form a read-back would return."""
    return RawShape(
        id=shape_id,
        type=shape.type,
        frame=shape.frame,
        label_id=shape.label_id,
        points=list(shape.points),
        occluded=False,
        z_order=0,
        rotation=0.0,
        source="manual",
        attributes=[],
        created_by="",
    )


class FakeCvatApi:
    """``CvatApiPort`` implementation that returns pre-built fixture data.

    Satisfies the ``CvatApiPort`` protocol structurally (duck-typing).
    Task-scoped methods can be made to fail for selected task ids via
    *fail_task_ids* / *fail_status* / *fail_methods*; every call to
    ``get_task_annotations`` is recorded in ``annotation_calls``.

    Write methods record their traffic on ``self.writes`` and keep the
    in-memory task store consistent (``create_task`` allocates an id,
    ``attach_task_data`` synthesizes frame metadata, ``set_deleted_frames``
    updates the stored ``data_meta``), so full upload flows run against the
    fake.  A ``MagicMock(spec=CvatApiPort)`` remains acceptable only for
    narrow single-method interaction tests (error injection, exact call-arg
    assertions where a one-line ``return_value`` beats fixture setup).

    *flaky* makes any method fail its first N calls and then succeed, which
    is what a retry policy has to be tested against: ``call_counts`` then
    says how many attempts it actually took.  Mutations are guarded by a
    lock so concurrent callers cannot interleave a read-modify-write.
    """

    def __init__(  # noqa: PLR0913
        self,
        fixtures: LoadedFixtures,
        *,
        fail_task_ids: Collection[int] = frozenset(),
        fail_status: int = 500,
        fail_methods: Collection[str] = _DEFAULT_FAIL_METHODS,
        flaky: Mapping[str, int] | None = None,
        flaky_status: int = 429,
        flaky_retry_after: float | None = None,
    ) -> None:
        """Unpack fixture data into internal stores (copies: writes stay local)."""
        self._project = fixtures.project
        self._tasks = list(fixtures.tasks)
        self._labels = fixtures.labels
        self._task_data = dict(fixtures.task_data)
        self._issues = dict(fixtures.issues or {})
        self._fail_task_ids = frozenset(fail_task_ids)
        self._fail_status = fail_status
        self._fail_methods = frozenset(fail_methods)
        self._flaky = dict(flaky or {})
        self._flaky_status = flaky_status
        self._flaky_retry_after = flaky_retry_after
        self._lock = threading.Lock()
        self.call_counts: Counter[str] = Counter()
        self.annotation_calls: list[int] = []
        self.writes = RecordedWrites()
        self.organizations: list[OrganizationInfo] = []
        self.organization: str | None = None
        self.organization_calls: list[str | None] = []
        self.other_projects: list[ProjectInfo] = []

    @classmethod
    def from_tasks(
        cls,
        tasks: list[TaskInfo],
        *,
        project_name: str = "fake",
        other_projects: Sequence[ProjectInfo] = (),
    ) -> FakeCvatApi:
        """Create a fake API serving only a project with the given tasks.

        ``other_projects`` are additional entries for ``list_projects`` that own
        no tasks. A single-project fake cannot tell a lookup that selects the
        right project from one that selects any project at all.
        """
        fixtures = LoadedFixtures(
            project=ProjectInfo(id=1, name=project_name),
            tasks=tasks,
            labels=[],
            task_data={},
        )
        fake = cls(fixtures)
        fake.other_projects = list(other_projects)
        return fake

    def _raise_if_failing(self, method: str, task_id: int) -> None:
        with self._lock:
            self.call_counts[method] += 1
        if task_id in self._fail_task_ids and method in self._fail_methods:
            raise CvatApiError("fake failure", status_code=self._fail_status)

    def _enter(self, method: str) -> None:
        """Count the call and fail it while *method* still owes failures."""
        with self._lock:
            self.call_counts[method] += 1
            remaining = self._flaky.get(method, 0)
            if remaining <= 0:
                return
            self._flaky[method] = remaining - 1
        raise CvatApiError(
            f"fake {method} failure",
            status_code=self._flaky_status,
            retry_after=self._flaky_retry_after,
        )

    # ------------------------------------------------------------------
    # Read port
    # ------------------------------------------------------------------

    def list_organizations(self) -> list[OrganizationInfo]:
        """Return organizations configured on the fake (empty by default)."""
        return list(self.organizations)

    def set_organization(self, org: str | None) -> None:
        """Record the org switch and remember the current org."""
        self.organization = org
        self.organization_calls.append(org)

    def list_projects(self) -> list[ProjectInfo]:
        """Return the fixture project plus any extra ones the test configured."""
        return [self._project, *self.other_projects]

    def get_project_tasks(self, _project_id: int) -> list[TaskInfo]:
        """Return tasks from fixture data."""
        return list(self._tasks)

    def get_task(self, task_id: int) -> TaskInfo:
        """Return one task by id, filling ``project_id`` from the fixture project."""
        for task in self._tasks:
            if task.id == task_id:
                if task.project_id is not None:
                    return task
                return task.model_copy(update={"project_id": self._project.id})
        raise CvatApiError(f"Task not found: {task_id}", status_code=404)

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
        """Return the number of frames in a task.

        A task that is not here answers 404, as CVAT does: ``upload
        --resume`` reads a task id out of its manifest and has to survive
        that task having been deleted in the UI meanwhile.
        """
        if task_id not in self._task_data:
            raise CvatApiError(f"Task not found: {task_id}", status_code=404)
        data_meta, _annotations = self._task_data[task_id]
        return len(data_meta.frames)

    # ------------------------------------------------------------------
    # Write port (records traffic; keeps the task store consistent)
    # ------------------------------------------------------------------

    def create_task(self, spec: UploadTaskSpec) -> int:
        """Allocate a task id and register an empty task."""
        self._enter("create_task")
        with self._lock:
            self.writes.created_tasks.append(spec)
            task_id = max((t.id for t in self._tasks), default=0) + 1
            self._task_data[task_id] = (RawDataMeta(frames=[]), RawAnnotations())
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

    def attach_task_data(self, task_id: int, spec: UploadTaskSpec) -> None:
        """Synthesize frame metadata for *task_id* from the spec."""
        self._enter("attach_task_data")
        data_meta = RawDataMeta(
            frames=[RawFrame(name=f, width=640, height=480) for f in spec.server_files]
        )
        with self._lock:
            _, annotations = self._task_data[task_id]
            self._task_data[task_id] = (data_meta, annotations)

    def put_task_shapes(self, task_id: int, shapes: list[NewShape]) -> None:
        """Record uploaded shapes and make them readable back off the task.

        CVAT's action here is CREATE, so the shapes join whatever the task
        already had. Reflecting that in the store is what lets a test tell
        an upload that ran once from one that ran twice — the distinction
        ``upload --resume`` exists to preserve.
        """
        self._enter("put_task_shapes")
        with self._lock:
            self.writes.shapes.setdefault(task_id, []).extend(shapes)
            data_meta, annotations = self._task_data[task_id]
            next_id = len(annotations.shapes)
            self._task_data[task_id] = (
                data_meta,
                dataclasses.replace(
                    annotations,
                    shapes=[
                        *annotations.shapes,
                        *(
                            _as_raw_shape(next_id + offset, shape)
                            for offset, shape in enumerate(shapes)
                        ),
                    ],
                ),
            )

    def create_issue(self, issue: NewIssue) -> None:
        """Record a created issue and make it readable back off the task.

        ``get_task_jobs`` hands out one job per task keyed by the task id,
        so the issue's ``job_id`` is the task it belongs to. Reflecting the
        write is what lets a test tell one upload from two — the very thing
        ``upload --resume`` reads the issues back to check.
        """
        self._enter("create_issue")
        with self._lock:
            self.writes.issues.append(issue)
            stored = self._issues.setdefault(issue.job_id, [])
            self._issues[issue.job_id] = [
                *stored,
                RawIssue(
                    id=len(stored),
                    frame=issue.frame,
                    resolved=False,
                    comments=[issue.message],
                ),
            ]

    def set_deleted_frames(self, task_id: int, frame_ids: list[int]) -> None:
        """Record deleted frames and update the stored ``data_meta``."""
        self._enter("set_deleted_frames")
        with self._lock:
            self.writes.deleted_frames[task_id] = list(frame_ids)
            data_meta, annotations = self._task_data[task_id]
            self._task_data[task_id] = (
                dataclasses.replace(data_meta, deleted_frames=list(frame_ids)),
                annotations,
            )

    def delete_shapes(self, task_id: int, shapes: list[RawShape]) -> None:
        """Record deleted shapes per task."""
        self._enter("delete_shapes")
        with self._lock:
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

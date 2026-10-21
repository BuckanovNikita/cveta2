"""Public API task ops contracts."""

from typing import TYPE_CHECKING

import pytest

import cveta2
from cveta2.domain.errors import (
    Cveta2Error,
)

if TYPE_CHECKING:
    from cveta2.application.ports.dtos import RawShape
    from tests.fixtures.fake_cvat_project import LoadedFixtures

from tests.api_helpers import _scoped


class TestTaskOpsApi:
    def test_delete_removes_the_resolved_task(
        self, normal_fake: "LoadedFixtures"
    ) -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        cveta2.task_delete(normal_fake.project.id, task.name, connection=connection)

        assert api.writes.deleted_tasks == [task.id]

    def test_drop_label_deletes_only_that_labels_shapes(
        self, normal_fake: "LoadedFixtures"
    ) -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]
        label = next(lbl for lbl in normal_fake.labels if lbl.name == "bowl")
        expected = _shapes_with_label(normal_fake, task.id, label.id)

        removed = cveta2.task_drop_label(
            normal_fake.project.id, task.id, "bowl", connection=connection
        )

        assert removed == len(expected)
        assert {s.label_id for s in api.writes.deleted_shapes[task.id]} == {label.id}

    def test_mark_deleted_requires_frames_or_images(
        self, normal_fake: "LoadedFixtures"
    ) -> None:
        _api, connection = _scoped(normal_fake)

        with pytest.raises(Cveta2Error, match="frame"):
            cveta2.task_mark_deleted(
                normal_fake.project.id,
                normal_fake.tasks[0].id,
                connection=connection,
            )

    def test_mark_deleted_by_image_names(self, normal_fake: "LoadedFixtures") -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]
        names = [f.name for f in normal_fake.task_data[task.id][0].frames]

        marked = cveta2.task_mark_deleted(
            normal_fake.project.id,
            task.id,
            images=names[:2],
            connection=connection,
        )

        assert marked == 2
        assert api.writes.deleted_frames[task.id] == [0, 1]

    def test_mark_deleted_by_frame_ids(self, normal_fake: "LoadedFixtures") -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        marked = cveta2.task_mark_deleted(
            normal_fake.project.id, task.id, frames=[3], connection=connection
        )

        assert marked == 1
        assert api.writes.deleted_frames[task.id] == [3]

    def test_mark_deleted_sums_disjoint_names_and_ids(
        self, normal_fake: "LoadedFixtures"
    ) -> None:
        """Disjoint sets make the total distinguish sum from either half."""
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]
        names = [f.name for f in normal_fake.task_data[task.id][0].frames]

        marked = cveta2.task_mark_deleted(
            normal_fake.project.id,
            task.id,
            images=[names[0]],
            frames=[5, 6],
            connection=connection,
        )

        assert marked == 3
        assert api.writes.deleted_frames[task.id] == [0, 5, 6]


class TestTaskSetStatusApi:
    def test_invalid_state_rejected_before_remote_call(self) -> None:
        with pytest.raises(Cveta2Error, match="state"):
            cveta2.task_set_status(1, 1, state="in-progress")  # type: ignore[arg-type]

    def test_invalid_stage_rejected_before_remote_call(self) -> None:
        with pytest.raises(Cveta2Error, match="stage"):
            cveta2.task_set_status(1, 1, stage="done")  # type: ignore[arg-type]

    def test_requires_stage_or_state(self) -> None:
        with pytest.raises(Cveta2Error, match="stage"):
            cveta2.task_set_status(1, 1)

    def test_stage_and_state_reach_every_job(
        self, normal_fake: "LoadedFixtures"
    ) -> None:
        """Both must be non-None at once to tell the two keywords apart."""
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        updated = cveta2.task_set_status(
            normal_fake.project.id,
            task.id,
            stage="acceptance",
            state="completed",
            connection=connection,
        )

        assert updated == 1
        assert api.writes.job_updates == [(task.id, "acceptance", "completed")]

    def test_stage_alone_is_accepted(self, normal_fake: "LoadedFixtures") -> None:
        """A valid stage with no state must pass all three guards."""
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        cveta2.task_set_status(
            normal_fake.project.id,
            task.id,
            stage="validation",
            connection=connection,
        )

        assert api.writes.job_updates == [(task.id, "validation", None)]

    def test_state_alone_is_accepted(self, normal_fake: "LoadedFixtures") -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        cveta2.task_set_status(
            normal_fake.project.id,
            task.id,
            state="rejected",
            connection=connection,
        )

        assert api.writes.job_updates == [(task.id, None, "rejected")]


def _shapes_with_label(
    fixtures: "LoadedFixtures", task_id: int, label_id: int
) -> "list[RawShape]":
    _meta, annotations = fixtures.task_data[task_id]
    return [s for s in annotations.shapes if s.label_id == label_id]

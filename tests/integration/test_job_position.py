"""Integration tests pinning CVAT's own definition of a finished task.

``job_stage``/``job_state`` replaced the ``task_status`` column on the
premise that CVAT reads a job as finished at ``acceptance``/``completed``
and a task as finished only when none of its jobs is left behind.  That
premise lives in the server, not in this repo, so it is asserted against
a running CVAT rather than restated in a unit test: every case below
compares the verdict :func:`completed_task_ids` reaches from the fetched
rows against the ``status`` the same CVAT reports for the task.

Requires a running, seeded CVAT + MinIO (see scripts/integration_up.sh).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from cveta2.client import CvatClient
from cveta2.dataset_partition import completed_task_ids
from tests.integration.test_upload import IMAGE_NAMES, _get_project_and_storage

if TYPE_CHECKING:
    from cveta2.models import TaskAnnotations

pytestmark = pytest.mark.integration

_IMAGES_PER_JOB = 2
_TASK_IMAGES = 4

# (first job position, second job position, whether CVAT calls the task done).
# The expectation is only a readability aid: each case also asserts against
# the status CVAT itself reports, so a server that changed its rule fails
# here rather than silently redefining what reaches dataset.csv.
_CASES = [
    (("acceptance", "completed"), ("acceptance", "completed"), True),
    (("acceptance", "completed"), ("annotation", "new"), False),
    (("acceptance", "completed"), ("validation", "in progress"), False),
    (("acceptance", "in progress"), ("acceptance", "completed"), False),
    (("acceptance", "rejected"), ("acceptance", "completed"), False),
]


def _fetch_task_rows(client: CvatClient, task_id: int) -> TaskAnnotations:
    """Fetch one task through the ordinary fetch path."""
    task = client.api.get_task(task_id)
    ctx = client.prepare_fetch(task.project_id or 0, task_selector=[task_id])
    fetched = client.fetch_one_task(client.api, task, ctx)
    assert fetched is not None, f"task {task_id} was skipped by the fetch"
    return fetched


class TestJobPositionDecidesCompletion:
    """The two columns must reproduce CVAT's task-level status exactly."""

    def test_our_verdict_tracks_cvats_task_status(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        with CvatClient(cfg) as client:
            task_id = client.create_upload_task(
                project_id=project_id,
                name="integration-job-position",
                image_names=IMAGE_NAMES[:_TASK_IMAGES],
                cloud_storage_id=cs_info.id,
                segment_size=_IMAGES_PER_JOB,
            )
            try:
                jobs = sorted(
                    client.api.get_task_jobs(task_id), key=lambda j: j.start_frame
                )
                assert len(jobs) == 2, (
                    f"expected the task to split into two jobs, got {len(jobs)} — "
                    f"segment_size={_IMAGES_PER_JOB} over {_TASK_IMAGES} images"
                )

                for first, second, expected_done in _CASES:
                    for job, (stage, state) in zip(jobs, (first, second), strict=True):
                        client.api.update_job(job.id, stage=stage, state=state)

                    fetched = _fetch_task_rows(client, task_id)
                    df = pd.DataFrame(fetched.to_csv_rows())
                    our_verdict = task_id in completed_task_ids(
                        df, fetched.deleted_images
                    )
                    cvat_status = client.api.get_task(task_id).status

                    assert our_verdict == (cvat_status == "completed"), (
                        f"jobs at {first} and {second}: we say "
                        f"{'completed' if our_verdict else 'in progress'}, "
                        f"CVAT reports {cvat_status!r}"
                    )
                    assert our_verdict is expected_done
            finally:
                client.delete_task(task_id)

    def test_each_job_reports_its_own_position(self) -> None:
        """Rows of two jobs at different points must not share one position."""
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        with CvatClient(cfg) as client:
            task_id = client.create_upload_task(
                project_id=project_id,
                name="integration-job-position-split",
                image_names=IMAGE_NAMES[:_TASK_IMAGES],
                cloud_storage_id=cs_info.id,
                segment_size=_IMAGES_PER_JOB,
            )
            try:
                jobs = sorted(
                    client.api.get_task_jobs(task_id), key=lambda j: j.start_frame
                )
                client.api.update_job(jobs[0].id, stage="acceptance", state="completed")
                client.api.update_job(jobs[1].id, stage="annotation", state="new")

                fetched = _fetch_task_rows(client, task_id)
                by_frame = {
                    record.frame_id: (record.job_stage, record.job_state)
                    for record in fetched.annotations
                }

                assert by_frame, "the fetch returned no rows to check"
                for frame, position in by_frame.items():
                    expected = (
                        ("acceptance", "completed")
                        if frame <= jobs[0].stop_frame
                        else ("annotation", "new")
                    )
                    assert position == expected, f"frame {frame}"
            finally:
                client.delete_task(task_id)

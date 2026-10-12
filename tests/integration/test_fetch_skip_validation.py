"""Prove project promotion and same-run export against owned live CVAT tasks."""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import cveta2
from cveta2.client import CvatClient
from cveta2.config import IgnoreConfig, IgnoredTask
from tests.integration.test_upload import IMAGE_NAMES, _get_project_and_storage

pytestmark = pytest.mark.integration


def _positions(client: CvatClient, task_id: int) -> dict[int, tuple[str, str]]:
    return {job.id: (job.stage, job.state) for job in client.api.get_task_jobs(task_id)}


def _assert_csv_membership(
    output: Path, owned_ids: set[int], accepted: set[int]
) -> None:
    exported_ids: set[int] = set()
    for filename in ("dataset.csv", "obsolete.csv"):
        rows = pd.read_csv(output / filename)
        own_rows = rows[rows["task_id"].isin(owned_ids)]
        exported_ids.update(own_rows["task_id"].astype(int))
        assert own_rows["job_stage"].eq("acceptance").all()
        assert own_rows["job_state"].eq("completed").all()
        assert own_rows["task_completed"].eq(True).all()  # noqa: FBT003
    assert exported_ids == accepted
    in_progress = pd.read_csv(output / "in_progress.csv")
    assert not in_progress["task_id"].isin(owned_ids).any()


def test_skip_validation_promotes_and_exports_completed_tasks(tmp_path: Path) -> None:
    project_id, project_name, cs_info, cfg = _get_project_and_storage()
    positions = (
        (("annotation", "completed"), ("annotation", "completed")),
        (("acceptance", "completed"), ("annotation", "completed")),
        (("annotation", "completed"), ("annotation", "new")),
        (("annotation", "completed"), ("annotation", "completed")),
    )
    task_ids: list[int] = []
    with CvatClient(cfg) as client:
        try:
            for index, job_positions in enumerate(positions):
                task_id = client.create_upload_task(
                    project_id=project_id,
                    name=f"{project_name} skip-validation-{index}",
                    image_names=IMAGE_NAMES[index * 2 : (index + 1) * 2],
                    cloud_storage_id=cs_info.id,
                    segment_size=1,
                )
                task_ids.append(task_id)
                jobs = sorted(
                    client.api.get_task_jobs(task_id), key=lambda job: job.start_frame
                )
                assert len(jobs) == 2
                for job, (stage, state) in zip(jobs, job_positions, strict=True):
                    client.api.update_job(job.id, stage=stage, state=state)

            initial = {task_id: _positions(client, task_id) for task_id in task_ids}
            ignored = IgnoreConfig(
                projects={
                    project_name: [
                        IgnoredTask(id=task_ids[3], name="ignored", silent=True)
                    ]
                }
            )
            connection = cveta2.Connection(client=client)
            with (
                patch("cveta2.config.IgnoreConfig.load", return_value=ignored),
                patch.object(
                    client.api, "update_job", wraps=client.api.update_job
                ) as updates,
            ):
                # Omit the new keyword: the ordinary fetch must never accept jobs.
                cveta2.fetch(
                    project_name,
                    tmp_path / "default",
                    completed_only=True,
                    download_images=False,
                    cache="off",
                    publish_clearml=False,
                    connection=connection,
                )
                updates.assert_not_called()
                assert {
                    task_id: _positions(client, task_id) for task_id in task_ids
                } == initial
                _assert_csv_membership(tmp_path / "default", set(task_ids), set())

                cveta2.fetch(
                    project_name,
                    tmp_path / "promoted",
                    skip_validation=True,
                    completed_only=True,
                    download_images=False,
                    cache="off",
                    publish_clearml=False,
                    connection=connection,
                )
                expected_jobs = {
                    job_id
                    for task_id in task_ids[:2]
                    for job_id, position in initial[task_id].items()
                    if position == ("annotation", "completed")
                }
                owned_jobs = {
                    job_id for task_jobs in initial.values() for job_id in task_jobs
                }
                actual_jobs = [
                    call.args[0]
                    for call in updates.call_args_list
                    if call.args[0] in owned_jobs
                ]
                assert set(actual_jobs) == expected_jobs
                assert len(actual_jobs) == len(expected_jobs)
                for task_id in task_ids[:2]:
                    assert set(_positions(client, task_id).values()) == {
                        ("acceptance", "completed")
                    }
                    assert client.api.get_task(task_id).status == "completed"
                for task_id in task_ids[2:]:
                    assert _positions(client, task_id) == initial[task_id]
                _assert_csv_membership(
                    tmp_path / "promoted", set(task_ids), set(task_ids[:2])
                )

                updates.reset_mock()
                cveta2.fetch(
                    project_name,
                    tmp_path / "rerun",
                    skip_validation=True,
                    completed_only=True,
                    download_images=False,
                    cache="off",
                    publish_clearml=False,
                    connection=connection,
                )
                updates.assert_not_called()
                _assert_csv_membership(
                    tmp_path / "rerun", set(task_ids), set(task_ids[:2])
                )
        finally:
            for task_id in reversed(task_ids):
                client.delete_task(task_id)

"""Integration tests for task write operations (mark-deleted, drop-label, etc).

Requires a running, seeded CVAT + MinIO (see scripts/integration_up.sh).
Uses coco8-dev project and images seeded by seed_cvat.py.
"""

from __future__ import annotations

import pandas as pd
import pytest

from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.client import CvatClient
from cveta2.exceptions import Cveta2Error
from tests.integration.conftest import _make_sdk_client
from tests.integration.test_upload import IMAGE_NAMES, _get_project_and_storage

pytestmark = pytest.mark.integration


def _create_task(
    client: CvatClient,
    project_id: int,
    cloud_storage_id: int,
    name: str,
    num_images: int,
) -> int:
    """Create a task in coco8-dev with the first *num_images* seeded images."""
    return client.create_upload_task(
        project_id=project_id,
        name=name,
        image_names=IMAGE_NAMES[:num_images],
        cloud_storage_id=cloud_storage_id,
        segment_size=10,
    )


class TestMarkFramesDeletedByIdsIntegration:
    """mark_frames_deleted_by_ids: frame IDs land in data_meta.deleted_frames."""

    def test_mark_frames_deleted_by_ids(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        with CvatClient(cfg) as client:
            task_id = _create_task(
                client, project_id, cs_info.id, "integration-task-ops-mark-by-id", 3
            )
            marked = client.mark_frames_deleted_by_ids(task_id, [0, 2, 99])
        assert marked == 2
        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            data_meta = adapter.get_task_data_meta(task_id)
            assert sorted(data_meta.deleted_frames) == [0, 2]
        finally:
            sdk_client.close()


class TestDropLabelAnnotationsIntegration:
    """drop_label_annotations: only the other label's shapes remain."""

    def test_drop_label_keeps_other_labels(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        with CvatClient(cfg) as client:
            task_id = _create_task(
                client, project_id, cs_info.id, "integration-task-ops-drop-label", 2
            )
            ann_df = pd.DataFrame(
                [
                    {
                        "image_name": IMAGE_NAMES[0],
                        "instance_label": "person",
                        "bbox_x_tl": 10.0,
                        "bbox_y_tl": 20.0,
                        "bbox_x_br": 110.0,
                        "bbox_y_br": 120.0,
                    },
                    {
                        "image_name": IMAGE_NAMES[1],
                        "instance_label": "car",
                        "bbox_x_tl": 30.0,
                        "bbox_y_tl": 40.0,
                        "bbox_x_br": 130.0,
                        "bbox_y_br": 140.0,
                    },
                ]
            )
            uploaded = client.upload_task_annotations(
                task_id=task_id, annotations_df=ann_df
            )
            assert uploaded == 2
            assert client.count_task_label_shapes(task_id, "person") == 1
            deleted = client.drop_label_annotations(task_id, "person")
        assert deleted == 1
        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            annotations = adapter.get_task_annotations(task_id)
            labels = adapter.get_project_labels(project_id)
            car_ids = {lbl.id for lbl in labels if lbl.name == "car"}
            assert len(annotations.shapes) == 1
            assert annotations.shapes[0].label_id in car_ids
        finally:
            sdk_client.close()

    def test_drop_unknown_label_raises(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        with CvatClient(cfg) as client:
            task_id = _create_task(
                client, project_id, cs_info.id, "integration-task-ops-drop-unknown", 1
            )
            with pytest.raises(Cveta2Error, match="no-such-label"):
                client.drop_label_annotations(task_id, "no-such-label")


class TestSetTaskJobsStatusIntegration:
    """set_task_jobs_status: jobs report the new stage/state."""

    def test_status_update_reflected_on_jobs(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        with CvatClient(cfg) as client:
            task_id = _create_task(
                client, project_id, cs_info.id, "integration-task-ops-status", 2
            )
            num_jobs = client.set_task_jobs_status(
                task_id, stage="validation", state="in progress"
            )
        assert num_jobs >= 1
        sdk_client = _make_sdk_client()
        try:
            task = sdk_client.tasks.retrieve(task_id)
            for job in task.get_jobs():
                assert str(job.stage) == "validation"
                assert str(job.state) == "in progress"
        finally:
            sdk_client.close()


class TestDeleteTaskIntegration:
    """delete_task: task disappears from list_project_tasks."""

    def test_delete_task_removes_it(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        with CvatClient(cfg) as client:
            task_id = _create_task(
                client, project_id, cs_info.id, "integration-task-ops-delete", 1
            )
            task_ids_before = {t.id for t in client.list_project_tasks(project_id)}
            assert task_id in task_ids_before
            client.delete_task(task_id)
            task_ids_after = {t.id for t in client.list_project_tasks(project_id)}
        assert task_id not in task_ids_after

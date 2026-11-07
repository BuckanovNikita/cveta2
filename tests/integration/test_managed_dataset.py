"""Owned live CVAT + MinIO CSV + ClearML managed publication and reuse."""

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

import boto3
import pandas as pd
import pytest
import yaml
from PIL import Image

from cveta2.adapters.cvat.sdk_adapter import SdkCvatApiAdapter
from cveta2.adapters.files.managed_sources import LocalSourceFiles
from cveta2.application.ports.dtos import RawAnnotations, RawJob
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.managed.preparation import ManagedRecord
from cveta2.domain.models import ProjectInfo
from cveta2.interfaces import managed_datasets as api
from tests.integration.clearml_run import RunSettings, project_name
from tests.integration.conftest import (
    _make_sdk_client,
    find_seeded_project,
    make_integration_config,
)

pytestmark = pytest.mark.integration
pytest_plugins = ("tests.integration.test_clearml",)


class ConfigPaths(TypedDict):
    config_path: Path
    project_config: Path


@pytest.fixture
def reviewed_seed_project(clearml_run: RunSettings) -> Iterator[ProjectInfo]:
    """Review two exact-owned tasks and restore every original job on teardown."""
    sdk = _make_sdk_client()
    adapter = SdkCvatApiAdapter(sdk)
    restore_jobs: list[RawJob] = []
    try:
        project = find_seeded_project(adapter)
        assert project.name.split(maxsplit=1)[0] == clearml_run.tag
        assert adapter.get_project(project.id) == project
        tasks = adapter.get_project_tasks(project.id)
        assert len(tasks) >= 2, "the owned seeded project must contain two tasks"
        assert all(task.project_id == project.id for task in tasks)
        for selected in sorted(tasks, key=lambda task: task.id, reverse=True)[:2]:
            assert adapter.get_task(selected.id).project_id == project.id
            jobs = adapter.get_task_jobs(selected.id)
            assert jobs, "the selected owned task must contain jobs"
            assert all(job.stage and job.state for job in jobs)
            # Record originals before each task's first possibly partial write.
            # A second reviewed task proves reuse independently of issue writes.
            restore_jobs.extend(jobs)
            for job in jobs:
                adapter.update_job(job.id, stage="acceptance", state="completed")
            assert adapter.get_task(selected.id).status == "completed"
        yield project
    finally:
        errors = []
        try:
            for job in reversed(restore_jobs):
                try:
                    adapter.update_job(job.id, stage=job.stage, state=job.state)
                except Cveta2Error as error:  # noqa: PERF203 - restore every job.
                    errors.append(f"job {job.id}: {error}")
        finally:
            sdk.close()
        if errors:
            pytest.fail("Could not restore owned CVAT jobs: " + "; ".join(errors))


def test_live_mixed_sources_publish_exact_payload_and_reuse_completed_tasks(  # noqa: PLR0915 - one owned full-lifecycle scenario.
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clearml_run: RunSettings,
    class_api: str,
    reviewed_seed_project: ProjectInfo,
) -> None:
    """Use only the seeded tagged project/bucket and exact-owned ClearML names."""
    from clearml import Dataset

    for target, source in (
        ("AWS_ENDPOINT_URL_S3", "MINIO_ENDPOINT"),
        ("AWS_ACCESS_KEY_ID", "MINIO_ACCESS_KEY"),
        ("AWS_SECRET_ACCESS_KEY", "MINIO_SECRET_KEY"),
        ("AWS_DEFAULT_REGION", "MINIO_REGION"),
    ):
        monkeypatch.setenv(target, os.environ[source])
    bucket = os.environ["MINIO_BUCKET"]
    assert bucket == clearml_run.tag
    cfg = make_integration_config()
    project = reviewed_seed_project

    images = tmp_path / "images"
    images.mkdir()
    external_rows = []
    for index in range(16):
        name = f"managed-external-{index}.png"
        color = tuple(hashlib.sha256(name.encode()).digest()[:3])
        Image.new("RGB", (32, 32), color).save(images / name)
        external_rows.append(
            {
                "image_name": name,
                "image_path": str(images / name),
                "instance_label": "cat",
                "bbox_x_tl": 1,
                "bbox_y_tl": 1,
                "bbox_x_br": 20,
                "bbox_y_br": 20,
            }
        )
    object_key = f"managed-source/{uuid4().hex}.csv"
    s3 = boto3.client("s3", endpoint_url=os.environ["MINIO_ENDPOINT"])
    s3.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=pd.DataFrame(external_rows).to_csv(index=False).encode(),
    )
    try:
        shared = tmp_path / "project-config.yaml"
        shared.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "cvat": {"host": cfg.host, "organization": cfg.organization},
                    "projects": {"seeded": {"id": project.id, "name": project.name}},
                    "datasets": {
                        "combined": {
                            "sources": [
                                {"name": "cvat", "type": "cvat", "project": "seeded"},
                                {
                                    "name": "supplemental",
                                    "type": "s3-csv",
                                    "uri": f"s3://{bucket}/{object_key}",
                                },
                            ],
                            "clearml": {
                                "project": project_name(clearml_run.tag, "managed-dataset"),
                                "dataset": f"{clearml_run.tag}-{uuid4().hex[:8]}",
                            },
                            "api_url": class_api,
                            "s3_roots": [f"s3://{bucket}"],
                        }
                    },
                }
            )
        )
        personal = tmp_path / "personal.yaml"
        personal.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "project_config": str(shared),
                    "cvat": {"username": cfg.username, "password": cfg.password},
                    "cache": {"images_root": str(images)},
                }
            )
        )
        options: ConfigPaths = {"config_path": personal, "project_config": shared}
        shared_bytes = shared.read_bytes()
        fetched = tmp_path / "fetched"
        api.fetch_dataset("combined", output_dir=fetched, **options)
        snapshot = LocalSourceFiles().read_snapshot(fetched)
        assert snapshot.parent_id is None, "configured sources must support cold start"
        frame = pd.read_csv(fetched / "dataset.csv", keep_default_na=False)
        assert set(frame["source_id"]) == {"cvat", "supplemental"}
        # An opaque external transform may choose one annotation per image and
        # normalize classes/coordinates; it retains explicit source lineage.
        transformed = frame.drop_duplicates("image_name").copy()
        for name in transformed["image_name"]:
            color = tuple(hashlib.sha256(str(name).encode()).digest()[:3])
            Image.new("RGB", (32, 32), color).save(images / str(name))
        transformed["image_path"] = transformed["image_name"].map(lambda name: str(images / str(name)))
        transformed["instance_label"] = "cat"
        transformed["instance_shape"] = "box"
        transformed["image_width"] = 32
        transformed["image_height"] = 32
        for column, value in (
            ("bbox_x_tl", 1),
            ("bbox_y_tl", 1),
            ("bbox_x_br", 20),
            ("bbox_y_br", 20),
        ):
            transformed[column] = value
        cvat_rows = transformed.loc[transformed["source_id"].eq("cvat")]
        assert not cvat_rows.empty
        bad_position = cvat_rows.index[0]
        bad_image = str(transformed.loc[bad_position, "image_name"])
        bad_task = int(transformed.loc[bad_position, "source_task_id"])
        bad_frame = int(transformed.loc[bad_position, "source_frame_id"])
        transformed.loc[bad_position, "bbox_x_br"] = 1
        transformed_path = tmp_path / "transformed.csv"
        transformed.to_csv(transformed_path, index=False)
        prepared = tmp_path / "prepared"
        summary = api.prepare_managed_dataset(
            "combined",
            transformed_path,
            source=fetched,
            output_dir=prepared,
            clean=True,
            **options,
        )
        assert summary.ready, summary.report
        assert json.loads((prepared / "preparation.json").read_bytes())["parent_id"] is None
        record = ManagedRecord.model_validate_json((prepared / "preparation.json").read_bytes())
        finding = next(
            finding for finding in record.findings if finding.task_id == bad_task and finding.frame_id == bad_frame
        )
        first_feedback = api.report_dataset_errors(prepared, **options)
        assert first_feedback.created >= 1
        assert first_feedback.failed == []
        assert first_feedback.unmapped == 0
        repeated_feedback = api.report_dataset_errors(prepared, **options)
        assert repeated_feedback.created == 0
        assert repeated_feedback.existing >= 1
        assert repeated_feedback.failed == []
        assert repeated_feedback.unmapped == 0
        sdk = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk)
            marker = f"[{finding.marker}]"
            assert any(
                issue.frame == bad_frame and any(marker in comment for comment in issue.comments)
                for issue in adapter.get_task_issues(bad_task)
            )
            current_tasks = {task.id: task for task in adapter.get_project_tasks(project.id)}
        finally:
            sdk.close()
        publication = api.publish_dataset(prepared, **options)
        remote = Dataset.get(dataset_id=publication.dataset_id)
        assert remote.is_final()
        assert set(remote.list_files()) == {"dataset.csv", "dataset.yaml", "tasks.yaml"}
        local = Path(remote.get_local_copy(use_soft_links=False))
        assert (local / "tasks.yaml").read_bytes() == (prepared / "tasks.yaml").read_bytes()
        assert {item.type for item in LocalSourceFiles().read_snapshot(local / "tasks.yaml").sources} == {
            "cvat",
            "s3-csv",
        }
        clean_rows = pd.read_csv(local / "dataset.csv", keep_default_na=False)
        assert len(clean_rows) == len(transformed) - 1
        assert bad_image not in set(clean_rows["image_name"])
        completed_ids = {task.id for item in snapshot.sources for task in item.tasks.values() if task.completed}
        assert len(completed_ids) >= 2
        # Issue writes may advance one task's timestamp. Its reviewed snapshot
        # may conservatively trigger one refetch; unchanged tasks must be reused.
        unchanged_completed_ids = {
            task.id
            for item in snapshot.sources
            for task in item.tasks.values()
            if task.completed and current_tasks[task.id].updated_date == task.updated_date
        }
        assert unchanged_completed_ids - {bad_task}
        annotation_reads: list[int] = []
        original = SdkCvatApiAdapter.get_task_annotations

        def tracked_read(self: SdkCvatApiAdapter, task_id: int) -> RawAnnotations:
            annotation_reads.append(task_id)
            return original(self, task_id)

        monkeypatch.setattr(SdkCvatApiAdapter, "get_task_annotations", tracked_read)
        api.fetch_dataset("combined", output_dir=tmp_path / "again", **options)
        assert unchanged_completed_ids.isdisjoint(annotation_reads)
        assert shared.read_bytes() == shared_bytes
    finally:
        # This exact object belongs to this case in the already owned run bucket.
        s3.delete_object(Bucket=bucket, Key=object_key)
        s3.close()

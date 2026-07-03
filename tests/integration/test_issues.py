"""Integration tests for CVAT issues sync (issue_text / issue_state columns).

Requires a running, seeded CVAT + MinIO (see scripts/integration_up.sh).
Uses coco8-dev project and images seeded by seed_cvat.py.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest
from cvat_sdk.api_client import models as cvat_models
from cvat_sdk.core.helpers import get_paginated_collection

from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.client import CvatClient
from tests.integration.conftest import _make_sdk_client
from tests.integration.test_upload import (
    IMAGE_NAMES,
    _cs_info_for_host,
    _get_project_and_storage,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.config import CvatConfig
    from cveta2.models import AnnotationRecord

pytestmark = pytest.mark.integration

_ISSUE_MESSAGE = "проблема с разметкой"


def _create_issue_via_sdk(task_id: int, frame: int, message: str) -> int:
    """Create an open issue on *task_id* via the raw SDK; return its ID."""
    sdk_client = _make_sdk_client()
    try:
        jobs = get_paginated_collection(
            sdk_client.api_client.jobs_api.list_endpoint,
            task_id=task_id,
        )
        issue, _ = sdk_client.api_client.issues_api.create(
            cvat_models.IssueWriteRequest(
                frame=frame,
                position=[0.0, 0.0, 10.0, 10.0],
                job=int(jobs[0].id),
                message=message,
            ),
        )
        return int(issue.id)
    finally:
        sdk_client.close()


def _resolve_issue_via_sdk(issue_id: int) -> None:
    sdk_client = _make_sdk_client()
    try:
        sdk_client.api_client.issues_api.partial_update(
            issue_id,
            patched_issue_write_request=cvat_models.PatchedIssueWriteRequest(
                resolved=True,
            ),
        )
    finally:
        sdk_client.close()


def _fetch_frame_records(
    cfg: CvatConfig, project_id: int, task_name: str, frame_id: int
) -> list[AnnotationRecord]:
    with CvatClient(cfg) as client:
        result = client.fetch_annotations(project_id, task_selector=[task_name])
    return [r for r in result.annotations if r.frame_id == frame_id]


class TestFetchIssuesIntegration:
    """Issues created in CVAT appear in fetched records with correct state."""

    def test_issue_lifecycle_reflected_in_fetch(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        task_name = "integration-issues-fetch-test"
        with CvatClient(cfg) as client:
            task_id = client.create_upload_task(
                project_id=project_id,
                name=task_name,
                image_names=IMAGE_NAMES[:2],
                cloud_storage_id=cs_info.id,
                segment_size=10,
            )

        issue_id = _create_issue_via_sdk(task_id, frame=0, message=_ISSUE_MESSAGE)

        records = _fetch_frame_records(cfg, project_id, task_name, frame_id=0)
        assert records, "expected records for frame 0"
        for record in records:
            assert record.issue_text == _ISSUE_MESSAGE
            assert record.issue_state == "open"

        other = _fetch_frame_records(cfg, project_id, task_name, frame_id=1)
        for record in other:
            assert record.issue_state == ""

        _resolve_issue_via_sdk(issue_id)

        records = _fetch_frame_records(cfg, project_id, task_name, frame_id=0)
        for record in records:
            assert record.issue_text == _ISSUE_MESSAGE
            assert record.issue_state == "resolved"


class TestUploadIssuesFromCsvIntegration:
    """run_upload creates open issues from rows with issue_state="new"."""

    def test_upload_csv_with_new_issue_creates_open_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cveta2.commands.upload import run_upload

        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        task_name = "integration-issues-upload-test"
        issue_message = "нужно проверить кадр"
        dataset_csv = tmp_path / "dataset.csv"
        pd.DataFrame(
            [
                {
                    "image_name": IMAGE_NAMES[0],
                    "instance_label": "person",
                    "instance_shape": "box",
                    "bbox_x_tl": 10.0,
                    "bbox_y_tl": 20.0,
                    "bbox_x_br": 110.0,
                    "bbox_y_br": 120.0,
                    "issue_text": issue_message,
                    "issue_state": "new",
                },
                {
                    "image_name": IMAGE_NAMES[1],
                    "instance_label": "car",
                    "instance_shape": "box",
                    "bbox_x_tl": 30.0,
                    "bbox_y_tl": 40.0,
                    "bbox_x_br": 130.0,
                    "bbox_y_br": 140.0,
                    "issue_text": "",
                    "issue_state": "",
                },
            ]
        ).to_csv(dataset_csv, index=False, encoding="utf-8")
        monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "no-config.yaml"))
        upload_args = argparse.Namespace(
            dataset=str(dataset_csv),
            in_progress=None,
            name=task_name,
            project=str(project_id),
            image_dir=None,
            complete=False,
            mark_all_deleted=False,
        )
        with (
            patch("cveta2.commands._bootstrap.CvatConfig.load", return_value=cfg),
            patch(
                "cveta2.commands.upload._select_labels",
                return_value=["person", "car"],
            ),
            patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
            patch(
                "cveta2.client.CvatClient.detect_project_cloud_storage",
                return_value=_cs_info_for_host(cs_info),
            ),
        ):
            run_upload(upload_args)

        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            tasks = adapter.get_project_tasks(project_id)
            task = next(t for t in tasks if t.name == task_name)
            issues = adapter.get_task_issues(task.id)
            assert len(issues) == 1
            assert issues[0].resolved is False
            assert issues[0].comments == [issue_message]
        finally:
            sdk_client.close()

    def test_same_text_on_two_bboxes_creates_two_issues(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cveta2.commands.upload import run_upload

        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        task_name = "integration-issues-multibbox-test"
        issue_message = "проверить оба бокса"
        dataset_csv = tmp_path / "dataset.csv"
        base_row = {
            "image_name": IMAGE_NAMES[0],
            "instance_label": "person",
            "instance_shape": "box",
            "issue_text": issue_message,
            "issue_state": "new",
        }
        pd.DataFrame(
            [
                {
                    **base_row,
                    "bbox_x_tl": 10.0,
                    "bbox_y_tl": 20.0,
                    "bbox_x_br": 110.0,
                    "bbox_y_br": 120.0,
                },
                {
                    **base_row,
                    "bbox_x_tl": 200.0,
                    "bbox_y_tl": 210.0,
                    "bbox_x_br": 300.0,
                    "bbox_y_br": 310.0,
                },
            ]
        ).to_csv(dataset_csv, index=False, encoding="utf-8")
        monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "no-config.yaml"))
        upload_args = argparse.Namespace(
            dataset=str(dataset_csv),
            in_progress=None,
            name=task_name,
            project=str(project_id),
            image_dir=None,
            complete=False,
            mark_all_deleted=False,
        )
        with (
            patch("cveta2.commands._bootstrap.CvatConfig.load", return_value=cfg),
            patch(
                "cveta2.commands.upload._select_labels",
                return_value=["person"],
            ),
            patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
            patch(
                "cveta2.client.CvatClient.detect_project_cloud_storage",
                return_value=_cs_info_for_host(cs_info),
            ),
        ):
            run_upload(upload_args)

        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            tasks = adapter.get_project_tasks(project_id)
            task = next(t for t in tasks if t.name == task_name)
            issues = adapter.get_task_issues(task.id)
            assert len(issues) == 2
            for issue in issues:
                assert issue.resolved is False
                assert issue.comments == [issue_message]
            raw_issues = get_paginated_collection(
                sdk_client.api_client.issues_api.list_endpoint,
                task_id=task.id,
            )
            positions = sorted(list(issue.position) for issue in raw_issues)
            assert positions == [
                [10.0, 20.0, 110.0, 120.0],
                [200.0, 210.0, 300.0, 310.0],
            ]
        finally:
            sdk_client.close()

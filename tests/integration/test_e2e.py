"""End-to-end tests against a live CVAT instance.

These tests exercise code paths that the parameterized fixture tests
cannot reach: real SdkCvatApiAdapter round-trips, real CvatClient
usage, and real CLI invocation without mocks.

Requires a running, seeded CVAT (see scripts/integration_up.sh).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    ImageWithoutAnnotations,
)
from tests.integration.conftest import _env, _make_sdk_client

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.integration

EXPECTED_TASK_COUNT = 7
EXPECTED_LABEL_COUNT = 80


class TestSdkAdapterRoundTrip:
    """Verify SdkCvatApiAdapter works against real CVAT."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> Iterator[None]:
        self.client = _make_sdk_client()
        self.adapter = SdkCvatApiAdapter(self.client)
        yield
        self.client.close()

    def test_list_projects(self) -> None:
        projects = self.adapter.list_projects()
        names = {p.name for p in projects}
        assert "coco8-dev" in names

    def test_get_project_tasks(self) -> None:
        projects = self.adapter.list_projects()
        project = next(p for p in projects if p.name == "coco8-dev")
        tasks = self.adapter.get_project_tasks(project.id)
        assert len(tasks) == EXPECTED_TASK_COUNT
        task_names = {t.name for t in tasks}
        assert "normal" in task_names
        assert "all-empty" in task_names
        assert "all-removed" in task_names

    def test_get_project_labels(self) -> None:
        projects = self.adapter.list_projects()
        project = next(p for p in projects if p.name == "coco8-dev")
        labels = self.adapter.get_project_labels(project.id)
        assert len(labels) == EXPECTED_LABEL_COUNT
        label_names = {lbl.name for lbl in labels}
        assert "person" in label_names
        assert "car" in label_names
        assert "dog" in label_names

    def test_get_task_data_meta(self) -> None:
        projects = self.adapter.list_projects()
        project = next(p for p in projects if p.name == "coco8-dev")
        tasks = self.adapter.get_project_tasks(project.id)
        normal_task = next(t for t in tasks if t.name == "normal")
        data_meta = self.adapter.get_task_data_meta(normal_task.id)
        assert len(data_meta.frames) == 8
        assert data_meta.deleted_frames == []
        frame_names = {f.name for f in data_meta.frames}
        assert "000000000009.jpg" in frame_names

    def test_get_task_annotations_normal(self) -> None:
        projects = self.adapter.list_projects()
        project = next(p for p in projects if p.name == "coco8-dev")
        tasks = self.adapter.get_project_tasks(project.id)
        normal_task = next(t for t in tasks if t.name == "normal")
        annotations = self.adapter.get_task_annotations(normal_task.id)
        assert len(annotations.shapes) == 30
        for s in annotations.shapes:
            assert s.type == "rectangle"

    def test_all_removed_task_has_deleted_frames(self) -> None:
        projects = self.adapter.list_projects()
        project = next(p for p in projects if p.name == "coco8-dev")
        tasks = self.adapter.get_project_tasks(project.id)
        task = next(t for t in tasks if t.name == "all-removed")
        data_meta = self.adapter.get_task_data_meta(task.id)
        assert sorted(data_meta.deleted_frames) == list(range(8))

    def test_frames_1_2_removed_task(self) -> None:
        projects = self.adapter.list_projects()
        project = next(p for p in projects if p.name == "coco8-dev")
        tasks = self.adapter.get_project_tasks(project.id)
        task = next(t for t in tasks if t.name == "frames-1-2-removed")
        data_meta = self.adapter.get_task_data_meta(task.id)
        assert sorted(data_meta.deleted_frames) == [1, 2]


class TestRealClientFetchAnnotations:
    """CvatClient.fetch_annotations with real SdkCvatApiAdapter."""

    def test_fetch_normal_project(self) -> None:
        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            host = _env("CVAT_INTEGRATION_HOST", "http://localhost:8080")
            cfg = CvatConfig(host=host)
            client = CvatClient(cfg, api=adapter)

            projects = adapter.list_projects()
            project = next(p for p in projects if p.name == "coco8-dev")
            result = client.fetch_annotations(project.id)

            bbox_records = [
                a for a in result.annotations if isinstance(a, BBoxAnnotation)
            ]
            without_records = [
                a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)
            ]

            assert len(bbox_records) > 0
            assert len(result.annotations) > 0
            all_frame_ids = {a.frame_id for a in bbox_records} | {
                w.frame_id for w in without_records
            }
            assert len(all_frame_ids) > 0

            rows = result.to_csv_rows()
            assert len(rows) > 0
            expected_keys = set(CSV_COLUMNS)
            for row in rows:
                assert set(row.keys()) == expected_keys
        finally:
            sdk_client.close()


class TestRealCliFetchTask:
    """Invoke run_fetch_task pointing at real CVAT."""

    def test_fetch_task_produces_csv(self, tmp_path: Path) -> None:
        import argparse

        from cveta2.commands.fetch import run_fetch_task
        from cveta2.config import IgnoreConfig

        host = _env("CVAT_INTEGRATION_HOST", "http://localhost:8080")
        username = _env("CVAT_INTEGRATION_USER", "admin")
        password = _env("CVAT_INTEGRATION_PASSWORD", "admin")

        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            projects = adapter.list_projects()
            project = next(p for p in projects if p.name == "coco8-dev")
            tasks = adapter.get_project_tasks(project.id)
            normal_task = next(t for t in tasks if t.name == "normal")
        finally:
            sdk_client.close()

        cfg = CvatConfig(host=host, username=username, password=password)
        out_dir = tmp_path / "out"

        args = argparse.Namespace(
            project=str(project.id),
            task=[normal_task.name],
            output_dir=str(out_dir),
            completed_only=False,
            no_images=True,
            images_dir=None,
            save_tasks=False,
        )

        from unittest.mock import patch

        with (
            patch("cveta2.commands.fetch.CvatConfig.load", return_value=cfg),
            patch("cveta2.commands.fetch.require_host"),
            patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
            patch(
                "cveta2.commands.fetch.load_ignore_config",
                return_value=IgnoreConfig(),
            ),
            patch(
                "cveta2.client.CvatClient.detect_project_cloud_storage",
                return_value=None,
            ),
        ):
            run_fetch_task(args)

        dataset_csv = out_dir / "dataset.csv"
        assert dataset_csv.exists()
        df = pd.read_csv(dataset_csv)
        assert len(df) > 0
        assert set(CSV_COLUMNS).issubset(set(df.columns))

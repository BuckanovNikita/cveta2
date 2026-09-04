"""End-to-end tests against a live CVAT instance.

These tests exercise code paths that the parameterized fixture tests
cannot reach: real SdkCvatApiAdapter round-trips, real CvatClient
usage, and real CLI invocation without mocks.

Requires a running, seeded CVAT (see scripts/integration_up.sh).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from cvat_sdk.api_client import models as cvat_models
from cvat_sdk.core.helpers import get_paginated_collection

from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    ImageWithoutAnnotations,
)
from cveta2.services.fetch import FetchOptions, FetchTarget, fetch_selected_tasks
from cveta2.task_cache import get_task_cache_dir
from tests.helpers import fetch_all_annotations
from tests.integration.conftest import _env, _make_sdk_client
from tests.integration.test_upload import (
    IMAGE_NAMES,
    _cs_info_for_host,
    _get_project_and_storage,
)

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
    """Full project fetch through the real SdkCvatApiAdapter."""

    def test_fetch_normal_project(self) -> None:
        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            host = _env("CVAT_INTEGRATION_HOST", "http://localhost:8080")
            cfg = CvatConfig(host=host)
            client = CvatClient(cfg, api=adapter)

            projects = adapter.list_projects()
            project = next(p for p in projects if p.name == "coco8-dev")
            result = fetch_all_annotations(client, project.id)

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


def _complete_task_jobs(task_id: int) -> None:
    """Move every job of *task_id* to acceptance/completed via the raw SDK."""
    sdk_client = _make_sdk_client()
    try:
        jobs = get_paginated_collection(
            sdk_client.api_client.jobs_api.list_endpoint, task_id=task_id
        )
        for job in jobs:
            sdk_client.api_client.jobs_api.partial_update(
                int(job.id),
                patched_job_write_request=cvat_models.PatchedJobWriteRequest(
                    stage=cvat_models.JobStage("acceptance"),
                    state=cvat_models.OperationStatus("completed"),
                ),
            )
    finally:
        sdk_client.close()


def _task_updated_date(
    adapter: SdkCvatApiAdapter, project_id: int, task_name: str
) -> str:
    """Read one task's live ``updated_date`` straight from CVAT."""
    tasks = adapter.get_project_tasks(project_id)
    return next(t for t in tasks if t.name == task_name).updated_date


class TestFetchTaskCacheLive:
    """Live round-trip of the task-annotation cache across two fetches."""

    def test_second_fetch_served_from_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id, project_name, cs_info, cfg = _get_project_and_storage()
        task_name = "integration-cache-roundtrip-test"
        with CvatClient(cfg) as client:
            task_id = client.create_upload_task(
                project_id=project_id,
                name=task_name,
                image_names=IMAGE_NAMES[:2],
                cloud_storage_id=cs_info.id,
                segment_size=10,
            )
        _complete_task_jobs(task_id)

        monkeypatch.delenv("CVETA2_DISABLE_CACHE", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            tasks = adapter.get_project_tasks(project_id)
            live_task = next(t for t in tasks if t.name == task_name)
            assert live_task.status == "completed"

            spy = MagicMock(wraps=adapter.get_task_annotations)
            monkeypatch.setattr(adapter, "get_task_annotations", spy)
            client = CvatClient(cfg, api=adapter)
            options = FetchOptions(task_selector=[task_name])
            with patch(
                "cveta2.client.CvatClient.detect_project_cloud_storage",
                return_value=_cs_info_for_host(cs_info),
            ):
                fetch_selected_tasks(
                    client,
                    FetchTarget(project_id, project_name, tmp_path / "out1", None),
                    options,
                )
                assert spy.call_count == 1
                entry = get_task_cache_dir(project_id) / f"task_{task_id}.json"
                assert entry.exists(), "first fetch must persist a local cache entry"

                fetch_selected_tasks(
                    client,
                    FetchTarget(project_id, project_name, tmp_path / "out2", None),
                    options,
                )
                assert spy.call_count == 1, "second fetch must be served from cache"
        finally:
            sdk_client.close()

        df1 = pd.read_csv(tmp_path / "out1" / "dataset.csv")
        df2 = pd.read_csv(tmp_path / "out2" / "dataset.csv")
        pd.testing.assert_frame_equal(df1, df2)

    def test_a_project_label_edit_refreshes_cache_without_changing_partition(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A live task date change refreshes the cache but not partition order.

        Editing a project's labels rewrites every task in the project and
        bumps its ``updated_date``.  The conservative freshness check must
        refetch that task, while partitioning by task id must still place the
        same rows in the same files.
        """
        project_id, project_name, cs_info, cfg = _get_project_and_storage()
        task_name = "integration-label-edit-test"
        with CvatClient(cfg) as client:
            task_id = client.create_upload_task(
                project_id=project_id,
                name=task_name,
                image_names=IMAGE_NAMES[:2],
                cloud_storage_id=cs_info.id,
                segment_size=10,
            )
        _complete_task_jobs(task_id)

        monkeypatch.delenv("CVETA2_DISABLE_CACHE", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            spy = MagicMock(wraps=adapter.get_task_annotations)
            monkeypatch.setattr(adapter, "get_task_annotations", spy)
            client = CvatClient(cfg, api=adapter)
            options = FetchOptions(task_selector=[task_name])
            with patch(
                "cveta2.client.CvatClient.detect_project_cloud_storage",
                return_value=_cs_info_for_host(cs_info),
            ):
                fetch_selected_tasks(
                    client,
                    FetchTarget(project_id, project_name, tmp_path / "before", None),
                    options,
                )
                before_date = _task_updated_date(adapter, project_id, task_name)

                probe = "cveta2-label-edit-probe"
                client.update_project_labels(project_id, add=[probe])
                try:
                    after_date = _task_updated_date(adapter, project_id, task_name)
                    assert after_date != before_date, (
                        "the premise of this change: a project label edit must "
                        "bump the task's updated_date"
                    )

                    fetch_selected_tasks(
                        client,
                        FetchTarget(project_id, project_name, tmp_path / "after", None),
                        options,
                    )
                    assert spy.call_count == 2, (
                        "an advanced task updated_date must invalidate the cache"
                    )
                finally:
                    # The seeded project is shared with every other test here,
                    # one of which pins its exact label count.
                    client.update_project_labels(
                        project_id,
                        delete=[
                            lbl.id
                            for lbl in adapter.get_project_labels(project_id)
                            if lbl.name == probe
                        ],
                    )
        finally:
            sdk_client.close()

        for name in ("dataset.csv", "deleted.csv"):
            before = pd.read_csv(tmp_path / "before" / name)
            after = pd.read_csv(tmp_path / "after" / name)
            if not before.empty:
                assert (before["task_updated_date"] != after["task_updated_date"]).all()
            pd.testing.assert_frame_equal(
                before.drop(columns="task_updated_date"),
                after.drop(columns="task_updated_date"),
            )


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
            no_cache=True,
            force=False,
        )

        from unittest.mock import patch

        with (
            patch("cveta2.commands._bootstrap.CvatConfig.load", return_value=cfg),
            patch("cveta2.commands._bootstrap.require_host"),
            patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
            patch(
                "cveta2.config.IgnoreConfig.load",
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

"""End-to-end tests against a live CVAT instance.

These tests exercise code paths that the parameterized fixture tests
cannot reach: real SdkCvatApiAdapter round-trips, real CvatClient
usage, and real CLI invocation without mocks.

Requires a running, seeded CVAT (see uv run python -m tests.integration.lifecycle up).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from cvat_sdk.api_client import models as cvat_models
from cvat_sdk.core.helpers import get_paginated_collection

from cveta2.adapters.config.settings import CvatConfig
from cveta2.adapters.cvat.sdk_adapter import SdkCvatApiAdapter
from cveta2.adapters.s3.task_cache import get_task_cache_dir
from cveta2.application.ports.dtos import NewShape
from cveta2.application.use_cases.fetch import FetchOptions, FetchTarget
from cveta2.composition.client import CvatClient
from cveta2.composition.workflows import fetch_selected_tasks
from cveta2.domain.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    ImageWithoutAnnotations,
)
from tests.helpers import fetch_all_annotations
from tests.integration.conftest import (
    _make_sdk_client,
    find_seeded_project,
    make_integration_config,
    seeded_project_name,
    session_cvat_host,
)
from tests.integration.test_upload import (
    IMAGE_NAMES,
    _cs_info_for_host,
    _get_project_and_storage,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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
        assert seeded_project_name() in names

    def test_get_project_tasks(self) -> None:
        project = find_seeded_project(self.adapter)
        tasks = self.adapter.get_project_tasks(project.id)
        assert len(tasks) == EXPECTED_TASK_COUNT
        task_names = {t.name for t in tasks}
        assert "normal" in task_names
        assert "all-empty" in task_names
        assert "all-removed" in task_names

    def test_get_project_labels(self) -> None:
        project = find_seeded_project(self.adapter)
        labels = self.adapter.get_project_labels(project.id)
        assert len(labels) == EXPECTED_LABEL_COUNT
        label_names = {lbl.name for lbl in labels}
        assert "person" in label_names
        assert "car" in label_names
        assert "dog" in label_names

    def test_get_task_data_meta(self) -> None:
        project = find_seeded_project(self.adapter)
        tasks = self.adapter.get_project_tasks(project.id)
        normal_task = next(t for t in tasks if t.name == "normal")
        data_meta = self.adapter.get_task_data_meta(normal_task.id)
        assert len(data_meta.frames) == 8
        assert data_meta.deleted_frames == []
        frame_names = {f.name for f in data_meta.frames}
        assert "000000000009.jpg" in frame_names

    def test_get_task_annotations_normal(self) -> None:
        project = find_seeded_project(self.adapter)
        tasks = self.adapter.get_project_tasks(project.id)
        normal_task = next(t for t in tasks if t.name == "normal")
        annotations = self.adapter.get_task_annotations(normal_task.id)
        assert len(annotations.shapes) == 30
        for s in annotations.shapes:
            assert s.type == "rectangle"

    def test_all_removed_task_has_deleted_frames(self) -> None:
        project = find_seeded_project(self.adapter)
        tasks = self.adapter.get_project_tasks(project.id)
        task = next(t for t in tasks if t.name == "all-removed")
        data_meta = self.adapter.get_task_data_meta(task.id)
        assert sorted(data_meta.deleted_frames) == list(range(8))

    def test_frames_1_2_removed_task(self) -> None:
        project = find_seeded_project(self.adapter)
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
            cfg = CvatConfig(host=session_cvat_host())
            client = CvatClient(cfg, api=adapter)

            project = find_seeded_project(adapter)
            result = fetch_all_annotations(client, project.id)

            bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
            without_records = [a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)]

            assert len(bbox_records) > 0
            assert len(result.annotations) > 0
            all_frame_ids = {a.frame_id for a in bbox_records} | {w.frame_id for w in without_records}
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
        jobs = get_paginated_collection(sdk_client.api_client.jobs_api.list_endpoint, task_id=task_id)
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


def _task_updated_date(adapter: SdkCvatApiAdapter, project_id: int, task_name: str) -> str:
    """Read one task's live ``updated_date`` straight from CVAT."""
    tasks = adapter.get_project_tasks(project_id)
    return next(t for t in tasks if t.name == task_name).updated_date


def _two_job_task_with_boxes(cfg: CvatConfig, project_id: int, cloud_storage_id: int, name: str) -> int:
    """Create a finished four-frame task of two jobs with one box in each job."""
    with CvatClient(cfg) as client:
        task_id = client.create_upload_task(
            project_id=project_id,
            name=name,
            image_names=IMAGE_NAMES[:4],
            cloud_storage_id=cloud_storage_id,
            segment_size=2,
        )
        label_id = client.api.get_project_labels(project_id)[0].id
        client.api.put_task_shapes(
            task_id,
            [
                NewShape(frame=0, label_id=label_id, points=[1, 1, 5, 5]),
                NewShape(frame=3, label_id=label_id, points=[2, 2, 6, 6]),
            ],
        )
    _complete_task_jobs(task_id)
    return task_id


_COUNTED_READS = (
    "get_task_jobs",
    "get_task_data_meta",
    "get_task_issues",
    "get_task_annotations",
    "get_job_annotations",
)


class _SpiedSession:
    """Cached fetches of one live task whose per-task CVAT reads are counted."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task_name: str) -> None:
        self.project_id, self.project_name, self.cs_info, self.cfg = _get_project_and_storage()
        self.task_name = task_name
        self._tmp_path = tmp_path
        self._sdk_client = _make_sdk_client()
        self.adapter = SdkCvatApiAdapter(self._sdk_client)
        self.spies = {name: MagicMock(wraps=getattr(self.adapter, name)) for name in _COUNTED_READS}
        for name, spy in self.spies.items():
            monkeypatch.setattr(self.adapter, name, spy)
        self._client = CvatClient(self.cfg, api=self.adapter)
        self._storage = patch(
            "cveta2.composition.client.CvatClient.detect_project_cloud_storage",
            return_value=_cs_info_for_host(self.cs_info),
        )

    def __enter__(self) -> Self:
        self._storage.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._storage.stop()
        self._sdk_client.close()

    def fetch(self, out: str, *, use_cache: bool = True) -> pd.DataFrame:
        fetch_selected_tasks(
            self._client,
            FetchTarget(self.project_id, self.project_name, self._tmp_path / out, None),
            FetchOptions(task_selector=[self.task_name], use_cache=use_cache),
        )
        return pd.read_csv(self._tmp_path / out / "dataset.csv")

    def counts(self) -> dict[str, int]:
        return {name: spy.call_count for name, spy in self.spies.items() if spy.call_count}

    def reset(self) -> None:
        for spy in self.spies.values():
            spy.reset_mock()

    def task_updated_date(self) -> str:
        return _task_updated_date(self.adapter, self.project_id, self.task_name)


def _spied_two_job_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task_name: str
) -> tuple[_SpiedSession, int]:
    """Create a finished two-job task with boxes and a counted, cache-enabled session for it."""
    monkeypatch.delenv("CVETA2_DISABLE_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    session = _SpiedSession(tmp_path, monkeypatch, task_name)
    task_id = _two_job_task_with_boxes(session.cfg, session.project_id, session.cs_info.id, task_name)
    return session, task_id


class TestFetchTaskCacheLive:
    """Live round-trip of the task-annotation cache across two fetches."""

    def test_second_fetch_served_from_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
            job_spy = MagicMock(wraps=adapter.get_job_annotations)
            monkeypatch.setattr(adapter, "get_job_annotations", job_spy)
            client = CvatClient(cfg, api=adapter)
            options = FetchOptions(task_selector=[task_name])
            with patch(
                "cveta2.composition.client.CvatClient.detect_project_cloud_storage",
                return_value=_cs_info_for_host(cs_info),
            ):
                fetch_selected_tasks(
                    client,
                    FetchTarget(project_id, project_name, tmp_path / "out1", None),
                    options,
                )
                assert spy.call_count == 1
                entries = list((get_task_cache_dir(project_id) / f"task_{task_id}").glob("job_*.json"))
                assert entries, "first fetch must persist a local cache entry per finished job"

                fetch_selected_tasks(
                    client,
                    FetchTarget(project_id, project_name, tmp_path / "out2", None),
                    options,
                )
                assert spy.call_count == 1, "second fetch must be served from cache"
                assert job_spy.call_count == 0, "an unchanged finished job must not be read again"
        finally:
            sdk_client.close()

        df1 = pd.read_csv(tmp_path / "out1" / "dataset.csv")
        df2 = pd.read_csv(tmp_path / "out2" / "dataset.csv")
        pd.testing.assert_frame_equal(df1, df2)

    def test_a_job_state_change_on_a_cached_task_is_noticed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A state-only change keeps the task "completed" with its date; the next fetch must see it (SIP-82).

        This is the case the old status-gated cache served stale: the stage
        stays ``acceptance``, so CVAT keeps the task status. Before the change
        the test proves a warm hit costs one request (the jobs list) and that
        cache-off, cold and warm fetches give identical rows in identical
        order, the live check that the job endpoint numbers frames within the
        task as the task endpoint does.
        """
        session, task_id = _spied_two_job_session(tmp_path, monkeypatch, "integration-cache-job-state-test")
        jobs = sorted(session.adapter.get_task_jobs(task_id), key=lambda job: job.start_frame)
        assert len(jobs) == 2, f"expected two jobs, got {jobs}"
        second = jobs[1]
        with session:
            cold = session.fetch("cold")
            cache_dir = get_task_cache_dir(session.project_id) / f"task_{task_id}"
            assert sorted(path.name for path in cache_dir.glob("job_*.json")) == sorted(
                f"job_{job.id}.json" for job in jobs
            )
            session.reset()
            warm = session.fetch("warm")
            assert session.counts() == {"get_task_jobs": 1}, "a warm hit must cost exactly the jobs request"
            off = session.fetch("off", use_cache=False)
            pd.testing.assert_frame_equal(off, cold)
            pd.testing.assert_frame_equal(off, warm)
            assert (cold["instance_shape"] == "box").sum() == 2

            before_date = session.task_updated_date()
            session.adapter.update_job(second.id, state="rejected")
            date_moved = session.task_updated_date() != before_date
            session.reset()
            moved = session.fetch("moved")
            job_reads = [call.args[0] for call in session.spies["get_job_annotations"].call_args_list]

        assert not moved["task_completed"].any(), "the rejected job must make the cached task unfinished"
        second_rows = moved[moved["frame_id"].between(second.start_frame, second.stop_frame)]
        assert set(second_rows["job_stage"]) == {"acceptance"}
        assert set(second_rows["job_state"]) == {"rejected"}
        columns = ["image_name", "instance_shape", "bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"]
        pd.testing.assert_frame_equal(moved[columns], off[columns])
        # Metadata and issues are keyed on every job, so both branches read them again.
        if date_moved:
            expected = {"get_task_jobs": 1, "get_task_data_meta": 1, "get_task_issues": 1, "get_task_annotations": 1}
            assert session.counts() == expected, "branch: CVAT moved the task date, every entry is stale"
        else:
            expected = {"get_task_jobs": 1, "get_task_data_meta": 1, "get_task_issues": 1, "get_job_annotations": 1}
            assert session.counts() == expected, "branch: task date unchanged, only the rejected job is read"
            assert job_reads == [second.id]

    def test_a_shape_edit_on_a_cached_task_is_noticed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A box added to a finished, cached job must appear in the next fetch."""
        session, task_id = _spied_two_job_session(tmp_path, monkeypatch, "integration-cache-shape-edit-test")
        with session:
            session.fetch("cold")
            session.reset()
            session.fetch("warm")
            assert session.counts() == {"get_task_jobs": 1}, "a warm hit must cost exactly the jobs request"
            label_id = session.adapter.get_project_labels(session.project_id)[0].id
            session.adapter.put_task_shapes(task_id, [NewShape(frame=2, label_id=label_id, points=[3, 3, 7, 7])])
            session.reset()
            edited = session.fetch("edited")

        boxes = edited[edited["instance_shape"] == "box"]
        assert sorted(boxes["frame_id"]) == [0, 2, 3]
        assert session.counts().get("get_task_annotations", 0) + session.counts().get("get_job_annotations", 0) >= 1

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
                "cveta2.composition.client.CvatClient.detect_project_cloud_storage",
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
                        "the premise of this change: a project label edit must bump the task's updated_date"
                    )

                    fetch_selected_tasks(
                        client,
                        FetchTarget(project_id, project_name, tmp_path / "after", None),
                        options,
                    )
                    assert spy.call_count == 2, "an advanced task updated_date must invalidate the cache"
                finally:
                    # The seeded project is shared with every other test here,
                    # one of which pins its exact label count.
                    client.update_project_labels(
                        project_id,
                        delete=[lbl.id for lbl in adapter.get_project_labels(project_id) if lbl.name == probe],
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

        from cveta2.adapters.config.settings import IgnoreConfig
        from cveta2.interfaces.commands.fetch import run_fetch_task

        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            project = find_seeded_project(adapter)
            tasks = adapter.get_project_tasks(project.id)
            normal_task = next(t for t in tasks if t.name == "normal")
        finally:
            sdk_client.close()

        cfg = make_integration_config()
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
            patch(
                "cveta2.interfaces.commands._bootstrap.CvatConfig.load",
                return_value=cfg,
            ),
            patch("cveta2.interfaces.commands._bootstrap.require_host"),
            patch(
                "cveta2.interfaces.commands._helpers.load_projects_cache",
                return_value=[],
            ),
            patch(
                "cveta2.adapters.config.settings.IgnoreConfig.load",
                return_value=IgnoreConfig(),
            ),
            patch(
                "cveta2.composition.client.CvatClient.detect_project_cloud_storage",
                return_value=None,
            ),
        ):
            run_fetch_task(args)

        dataset_csv = out_dir / "dataset.csv"
        assert dataset_csv.exists()
        df = pd.read_csv(dataset_csv)
        assert len(df) > 0
        assert set(CSV_COLUMNS).issubset(set(df.columns))

"""Verify the application client operates through supplied neutral ports."""

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cveta2.application.client import ApplicationClient
from cveta2.application.ports.client import ClientSettings
from cveta2.application.ports.cvat import CvatApiPort
from cveta2.application.ports.images import ImageReadPort
from cveta2.domain.models import ProjectAnnotations, TaskInfo
from cveta2.domain.storage import CloudStorageInfo, DownloadStats


def test_inner_client_imports_without_infrastructure() -> None:
    """Importing the aggregate must not even attempt loading an adapter."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys
class BlockInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('cveta2.adapters', 'cveta2.composition',
                                'cvat_sdk', 'boto3', 'clearml')):
            raise AssertionError('Forbidden infrastructure import: ' + fullname)
sys.meta_path.insert(0, BlockInfrastructure())
from cveta2.application.client import ApplicationClient
from cveta2.application.ports.cvat import CvatApiPort
from cveta2.application.ports.dtos import RawDataMeta
assert ApplicationClient and CvatApiPort and RawDataMeta
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_selected_tasks_use_injected_execution_and_settings() -> None:
    """Selection preserves order, worker limit, and resolved failure policy."""
    api = MagicMock(spec=CvatApiPort)
    tasks = {
        i: TaskInfo(
            id=i,
            name=str(i),
            project_id=7,
            status="completed",
            subset="",
            updated_date="",
        )
        for i in (12, 3)
    }
    api.get_task.side_effect = tasks.__getitem__
    api.get_project_labels.return_value = []
    runner = MagicMock(
        side_effect=lambda items, work, **_kwargs: list(map(work, items))
    )
    client = ApplicationClient(
        ClientSettings(
            host="https://example.test", cvat_workers=4, raise_on_failure=True
        ),
        images=MagicMock(spec=ImageReadPort),
        runner=runner,
        api=api,
    )

    ctx = client.prepare_fetch(7, task_selector=[12, 3, 12])

    assert [task.id for task in ctx.tasks] == [12, 3]
    assert ctx.host == "https://example.test"
    assert ctx.raise_on_failure is True
    assert runner.call_args.args[0] == [12, 3]
    assert runner.call_args.kwargs["max_workers"] == 4
    assert runner.call_args.kwargs["catch"] == ()
    api.get_project_tasks.assert_not_called()


def test_image_port_receives_storage_and_prefix_without_local_io() -> None:
    """Application image methods pass lexical paths and storage to the port."""
    api = MagicMock(spec=CvatApiPort)
    images = MagicMock(spec=ImageReadPort)
    images.download.return_value = DownloadStats(total=0)
    images.sync.return_value = DownloadStats(total=0)
    storage = CloudStorageInfo(id=2, bucket="bucket", prefix="raw", endpoint_url="")
    annotations = ProjectAnnotations(annotations=[], deleted_images=[])
    target = Path("unmaterialized/output")
    client = ApplicationClient(
        ClientSettings(), images=images, runner=MagicMock(), api=api
    )

    assert (
        client.download_images(
            annotations,
            target,
            project_id=7,
            project_cloud_storage=storage,
            ignored_prefix="raw",
        )
        is images.download.return_value
    )
    assert (
        client.sync_project_images(
            7, target, project_cloud_storage=storage, ignored_prefix="raw"
        )
        is images.sync.return_value
    )

    images.download.assert_called_once_with(
        annotations, target, project_cloud_storage=storage, ignored_prefix="raw"
    )
    images.sync.assert_called_once_with(storage, target, ignored_prefix="raw")
    api.get_project_cloud_storage.assert_not_called()


def test_owned_session_closes_with_original_failure_and_injected_api_is_borrowed() -> (
    None
):
    """Application owns supplied sessions while leaving injected APIs open."""
    api = MagicMock(spec=CvatApiPort)
    calls: list[object] = []
    error = ValueError("original failure")

    @contextmanager
    def session() -> Iterator[CvatApiPort]:
        calls.append("enter")
        try:
            yield api
        except ValueError as caught:
            calls.append(caught)
            raise
        finally:
            calls.append("exit")

    client = ApplicationClient(
        ClientSettings(),
        images=MagicMock(spec=ImageReadPort),
        runner=MagicMock(),
        session_factory=session,
    )

    def fail_in_session() -> None:
        with client as entered:
            assert entered is client
            assert client.api is api
            raise error

    with pytest.raises(ValueError, match="original failure"):
        fail_in_session()
    assert calls == ["enter", error, "exit"]
    assert not client.is_ready

    borrowed = ApplicationClient(
        ClientSettings(),
        images=MagicMock(spec=ImageReadPort),
        runner=MagicMock(),
        session_factory=session,
        api=api,
    )
    with borrowed:
        assert borrowed.api is api
    assert borrowed.is_ready
    assert calls == ["enter", error, "exit"]


def test_public_client_resolves_late_environment_and_worker_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public clients observe runtime settings changed after construction."""
    import pandas as pd

    from cveta2.adapters.config.settings import CvatConfig
    from cveta2.adapters.execution.concurrency import Workers, configure_workers
    from cveta2.application.ports.dtos import RawDataMeta, RawFrame, RawJob
    from cveta2.composition.client import CvatClient
    from cveta2.domain.models import LabelInfo

    api = MagicMock(spec=CvatApiPort)
    api.get_task.return_value = TaskInfo(
        id=1, name="task", project_id=7, status="completed", subset="", updated_date=""
    )
    api.get_project_labels.return_value = []
    api.get_task_jobs.return_value = [RawJob(id=9, start_frame=0, stop_frame=0)]
    api.get_task_labels.return_value = [LabelInfo(id=2, name="car")]
    api.get_task_data_meta.return_value = RawDataMeta(
        frames=[RawFrame(name="a.jpg", width=100, height=100)]
    )
    runner = MagicMock(
        side_effect=lambda items, work, **_kwargs: list(map(work, items))
    )
    monkeypatch.setattr("cveta2.composition.client.run_concurrent", runner)
    monkeypatch.delenv("CVETA2_RAISE_ON_FAILURE", raising=False)
    prior = Workers.s3, Workers.cvat
    client = CvatClient(CvatConfig(), api=api)
    try:
        monkeypatch.setenv("CVETA2_RAISE_ON_FAILURE", "true")
        configure_workers(s3=prior[0], cvat=3)
        ctx = client.prepare_fetch(7, task_selector=[1])
        assert ctx.raise_on_failure is True
        assert runner.call_args.kwargs["max_workers"] == 3

        configure_workers(s3=prior[0], cvat=4)
        assert client.set_task_jobs_status(1, stage="acceptance") == 1
        assert runner.call_args.kwargs["max_workers"] == 4

        configure_workers(s3=prior[0], cvat=5)
        rows = pd.DataFrame(
            [
                {
                    "image_name": "a.jpg",
                    "issue_state": "new",
                    "issue_text": "fix",
                    "bbox_x_tl": 0.0,
                    "bbox_y_tl": 0.0,
                    "bbox_x_br": 10.0,
                    "bbox_y_br": 10.0,
                }
            ]
        )
        assert client.create_task_issues(1, rows) == 1
        assert runner.call_args.kwargs["max_workers"] == 5
    finally:
        configure_workers(s3=prior[0], cvat=prior[1])


def test_public_client_observes_mutable_config_before_owned_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection settings and public identity use the same current config."""
    from cveta2.client import CvatClient
    from cveta2.config import CvatConfig

    cfg = CvatConfig(
        host="https://old.example", organization="old", username="u", password="p"
    )
    api = MagicMock(spec=CvatApiPort)
    api.get_project_tasks.return_value = []
    api.get_project_labels.return_value = []
    connected: list[tuple[str | None, str | None]] = []

    @contextmanager
    def open_session(resolved: CvatConfig, _factory: object) -> Iterator[CvatApiPort]:
        connected.append((resolved.host, resolved.organization))
        yield api

    monkeypatch.setattr("cveta2.composition.client.open_sdk_api", open_session)
    client = CvatClient(cfg)
    cfg.host = "https://new.example"
    cfg.organization = "new"

    assert client.host == cfg.host
    assert client.default_organization == cfg.organization
    with client:
        assert client.api is api
        assert connected == [(client.host, client.default_organization)]
        assert client.prepare_fetch(7).host == cfg.host
    cfg.host = ""
    cfg.organization = None
    assert client.host == ""
    assert client.default_organization is None

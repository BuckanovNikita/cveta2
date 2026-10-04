"""Live review regressions; injected failures affect only this run's client."""

import importlib.util
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2._concurrency import Workers, configure_workers
from cveta2.client import CvatClient
from cveta2.exceptions import CvatApiError, Cveta2Error
from cveta2.image_downloader import S3Syncer
from cveta2.s3_utils import make_s3_client
from cveta2.services.upload import (
    UploadOptions,
    UploadPlan,
    UploadRequest,
    upload_dataset,
)
from tests.integration.conftest import _make_sdk_client, seeded_project_name
from tests.integration.test_upload import (
    IMAGE_NAMES,
    _coco8_search_dirs,
    _cs_info_for_host,
    _get_project_and_storage,
)

pytestmark = pytest.mark.integration


def test_live_sync_collision_preflight_and_directory_accounting(tmp_path: Path) -> None:
    """Real MinIO keys reject aliases before writes; directories are failures."""
    _project_id, _name, storage, _cfg = _get_project_and_storage()
    storage = _cs_info_for_host(storage).model_copy(update={"prefix": "review-sync"})
    s3 = make_s3_client(storage.endpoint_url)
    keys = {"review-sync/a.jpg": b"first", "review-sync/b.jpg": b"second"}
    for key, data in keys.items():
        s3.put_object(Bucket=storage.bucket, Key=key, Body=data)
    destination = tmp_path / "sync"
    destination.mkdir()
    alias = destination / "b.jpg"
    alias.symlink_to(destination / "a.jpg")
    syncer = S3Syncer(destination)
    old_s3, old_cvat = Workers.s3, Workers.cvat
    configure_workers(s3=4, cvat=old_cvat)
    try:
        with pytest.raises(Cveta2Error):
            syncer.sync(storage)
        assert not (destination / "a.jpg").exists()
        assert alias.is_symlink()
        alias.unlink()
        directory = destination / "a.jpg"
        directory.mkdir(parents=True)
        stats = syncer.sync(storage)
        assert (stats.total, stats.downloaded, stats.cached, stats.failed) == (
            2,
            1,
            0,
            1,
        )
        assert directory.is_dir()
        assert (destination / "b.jpg").read_bytes() == b"second"
        directory.rmdir()
        stats = syncer.sync(storage)
        assert (stats.total, stats.downloaded, stats.cached, stats.failed) == (
            2,
            1,
            1,
            0,
        )
        assert directory.read_bytes() == b"first"
    finally:
        configure_workers(s3=old_s3, cvat=old_cvat)
        for key in keys:
            s3.delete_object(Bucket=storage.bucket, Key=key)


def _annotations(names: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "image_name": name,
                "instance_label": "person",
                "bbox_x_tl": float(index),
                "bbox_y_tl": 2.0,
                "bbox_x_br": 20.0,
                "bbox_y_br": 30.0,
            }
            for index, name in enumerate(names)
        ]
    )


def test_resume_after_injected_post_write_failure() -> None:
    """A real successful append followed by an injected 503 has one effect."""
    project_id, project_name, storage, cfg = _get_project_and_storage()
    names = IMAGE_NAMES[:2]
    request = UploadRequest(
        project_id=project_id,
        project_name=project_name,
        task_name="review-resume-post-write",
        plan=UploadPlan(_annotations(names), names, []),
        options=UploadOptions(search_dirs=_coco8_search_dirs()),
        labels=("person",),
    )
    with CvatClient(cfg) as client:
        original = client.upload_task_annotations

        def applied_then_failed(*args: object, **kwargs: object) -> int:
            original(*args, **kwargs)  # type: ignore[arg-type]
            raise CvatApiError("injected after successful append", 503, retry_after=0)

        with patch.object(
            client,
            "detect_project_cloud_storage",
            return_value=_cs_info_for_host(storage),
        ):
            with (
                patch.object(
                    client, "upload_task_annotations", side_effect=applied_then_failed
                ),
                pytest.raises(CvatApiError, match="injected"),
            ):
                upload_dataset(client, request)
            with patch.object(
                client,
                "upload_task_annotations",
                side_effect=AssertionError("duplicate append"),
            ):
                outcome = upload_dataset(client, replace(request, resume=True))
        session = client.open_task_session(outcome.task_id)
        assert len(session.api.get_task_annotations(outcome.task_id).shapes) == 2
        assert outcome.annotations == 2


def test_clone_real_task_specific_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator helper clones differing task sizes and frame sequences."""
    _project_id, _name, storage, cfg = _get_project_and_storage()
    path = Path(__file__).resolve().parents[2] / "scripts/clone_project_to_s3.py"
    spec = importlib.util.spec_from_file_location("review_clone_helper", path)
    assert spec is not None
    assert spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    tag = seeded_project_name().split()[0]
    source_name, destination_name = f"{tag} clone-source", f"{tag} clone-destination"
    sdk = _make_sdk_client()
    source = sdk.projects.create({"name": source_name, "labels": [{"name": "person"}]})
    try:
        with CvatClient(cfg) as client:
            for index, names in enumerate(
                (list(reversed(IMAGE_NAMES[:2])), IMAGE_NAMES[2:5])
            ):
                task_id = client.create_upload_task(
                    project_id=source.id,
                    name=f"review-source-{index}",
                    image_names=names,
                    cloud_storage_id=storage.id,
                )
                client.upload_task_annotations(task_id, _annotations(names))
        original_parse = helper.parse_cloud_storage

        def host_storage(raw: object) -> object:
            parsed = original_parse(raw)
            parsed.endpoint_url = _cs_info_for_host(storage).endpoint_url
            return parsed

        monkeypatch.setattr(helper, "parse_cloud_storage", host_storage)
        monkeypatch.setattr(helper.CvatConfig, "load", lambda: cfg)
        monkeypatch.setattr(helper, "make_client", lambda **_kwargs: _make_sdk_client())
        monkeypatch.setattr(
            "sys.argv",
            [
                str(path),
                "--source",
                source_name,
                "--dest",
                destination_name,
                "--cloud-storage-id",
                str(storage.id),
                "--s3-subdir",
                "review-clone",
            ],
        )
        helper.main()
        destination = next(
            project
            for project in sdk.projects.list()
            if project.name == destination_name
        )
        source_tasks = {task.name: task for task in source.get_tasks()}
        cloned = destination.get_tasks()
        assert len(cloned) == 2
        adapter = SdkCvatApiAdapter(sdk)
        for task in cloned:
            original_task = source_tasks[task.name]
            assert task.size == original_task.size
            for frame in range(task.size):
                assert (
                    task.get_frame(frame, quality="original").read()
                    == original_task.get_frame(frame, quality="original").read()
                )
            expected = adapter.get_task_annotations(original_task.id).shapes
            actual = adapter.get_task_annotations(task.id).shapes
            assert [(s.frame, s.points) for s in actual] == [
                (s.frame, s.points) for s in expected
            ]
    finally:
        for project in sdk.projects.list():
            if project.name in {source_name, destination_name}:
                project.remove()
        sdk.close()

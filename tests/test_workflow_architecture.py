"""Recording ports pin workflow effects and recovery write ordering."""

from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pandas as pd
import pytest

from cveta2.application.client import ApplicationClient
from cveta2.application.client.shared import FetchContext
from cveta2.application.ports.cache import CacheFactory, TaskCache
from cveta2.application.ports.manifests import ManifestStore
from cveta2.application.ports.storage import UploadStorage
from cveta2.application.ports.workflow_files import WorkflowFiles
from cveta2.application.settings import CacheProjectSettings
from cveta2.application.use_cases.fetch import (
    FetchDependencies,
    FetchOptions,
    FetchTarget,
    _promote_completed_annotations,
    fetch_selected_tasks,
)
from cveta2.application.use_cases.upload import (
    UploadDependencies,
    UploadOptions,
    UploadPlan,
    UploadRequest,
    upload_dataset,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import TaskAnnotations, TaskInfo
from cveta2.domain.storage import CloudStorageInfo
from cveta2.domain.upload import UploadManifest, new_manifest

if TYPE_CHECKING:
    from collections.abc import Callable


def _fetch_deps(cache: Mock, files: Mock) -> FetchDependencies:
    caches = Mock(spec=CacheFactory)
    caches.create.return_value = cache
    clock = Mock(return_value=0.0)
    runner = Mock(side_effect=lambda items, work, **_kwargs: [work(t) for t in items])
    return FetchDependencies(
        caches=caches,
        files=files,
        runner=runner,
        clock=clock,
        lock_factory=nullcontext,
        cache_settings=CacheProjectSettings(),
    )


def test_fetch_uses_supplied_cache_and_files_without_creating_output() -> None:
    """A cached selected-task fetch delegates every file effect to its port."""
    task = TaskInfo(
        id=12, name="task", status="completed", updated_date="now", subset=""
    )
    annotations = TaskAnnotations(
        annotations=[], deleted_images=[], task_id=12, task_name="task"
    )
    client = Mock(spec=ApplicationClient)
    client.prepare_fetch.return_value = FetchContext([task], {}, {})
    client.detect_project_cloud_storage.return_value = None
    cache = Mock(spec=TaskCache)
    cache.get.return_value = annotations
    files = Mock(spec=WorkflowFiles)
    output = Path("unmaterialized-workflow-output")
    files.prepare_tasks.return_value = output / ".tasks"
    deps = _fetch_deps(cache, files)

    result = fetch_selected_tasks(
        client, FetchTarget(7, "project", output), FetchOptions(), deps=deps
    )

    assert result == TaskAnnotations.merge([annotations])
    client.fetch_one_task.assert_not_called()
    files.prepare_tasks.assert_called_once_with(output)
    files.write_task_csv.assert_called_once_with(task, annotations, output / ".tasks")
    files.cleanup_tasks.assert_called_once_with(output / ".tasks")
    files.write_dataset_and_deleted.assert_called_once_with(result, output)
    cache.put.assert_not_called()
    cache.prune.assert_not_called()


def test_disabled_cache_promotion_strictly_invalidates_local_before_write() -> None:
    """Promotion requires local invalidation even when cache reads are disabled."""
    task = TaskInfo(
        id=12, name="task", status="annotation", updated_date="now", subset=""
    )
    client = Mock(spec=ApplicationClient)
    client.list_project_tasks.return_value = [task]
    client.api = Mock()
    client.api.get_task_jobs.return_value = [
        Mock(id=4, stage="annotation", state="completed")
    ]
    events: list[str] = []
    cache = Mock(spec=TaskCache)
    cache.invalidate.side_effect = lambda *_args, **_kwargs: events.append("invalidate")
    client.api.update_job.side_effect = lambda *_args, **_kwargs: events.append("patch")
    deps = _fetch_deps(cache, Mock(spec=WorkflowFiles))

    _promote_completed_annotations(
        client,
        FetchTarget(7, "project", Path("unused")),
        FetchOptions(use_cache=False),
        deps=deps,
    )

    assert events == ["invalidate", "patch"]
    cache.invalidate.assert_called_once_with(12, strict=True)
    cast("Mock", deps.caches).create.assert_called_once_with(
        7, None, deps.cache_settings, local_only=True
    )
    client.detect_project_cloud_storage.assert_not_called()

    events.clear()
    cache.invalidate.side_effect = OSError("cannot delete")
    client.api.update_job.reset_mock()
    with pytest.raises(Cveta2Error, match="кэш"):
        _promote_completed_annotations(
            client,
            FetchTarget(7, "project", Path("unused")),
            FetchOptions(use_cache=False),
            deps=deps,
        )
    client.api.update_job.assert_not_called()


def _upload_setup() -> tuple[Mock, UploadRequest, UploadDependencies, list[str]]:
    client = Mock(spec=ApplicationClient)
    client.host = "https://cvat.example"
    storage = CloudStorageInfo(id=2, bucket="images", prefix="project", endpoint_url="")
    client.detect_project_cloud_storage.return_value = storage
    client.upload_task_annotations.return_value = 0
    annotations = pd.DataFrame([{"image_name": "a.jpg", "instance_label": None}])
    request = UploadRequest(
        7,
        "project",
        "new task",
        UploadPlan(annotations, ["a.jpg"], []),
        UploadOptions(),
    )
    files = Mock(spec=WorkflowFiles)
    files.resolve_images.return_value = ({}, ["a.jpg"])
    files.enrich_dataframe_paths.return_value = annotations
    remote = Mock(spec=UploadStorage)
    remote.mapping.return_value = (
        {"a.jpg": "2026-10/a.jpg"},
        {"project/2026-10/a.jpg"},
    )
    manifests = Mock(spec=ManifestStore)
    manifests.load.return_value = None
    manifests.new.side_effect = lambda **kwargs: new_manifest(
        **kwargs, started_at="2026-10-14T00:00:00+00:00"
    )
    events: list[str] = []

    def checkpoint(manifest: UploadManifest, *, required: bool = False) -> None:
        if manifest.completed_counts is not None:
            events.append("save-completed")
        elif manifest.task_id is not None:
            events.append("save-id")
        elif manifest.creation_pending:
            events.append("save-pending")
        else:
            events.append("save-intent")
        if manifest.completed_counts is None:
            assert required

    manifests.save.side_effect = checkpoint
    manifests.delete.side_effect = lambda *_args, **_kwargs: events.append("delete")

    def create(**kwargs: object) -> int:
        events.append("create")
        cast("Callable[[int], None]", kwargs["on_created"])(42)
        events.append("attach")
        return 42

    client.create_upload_task.side_effect = create

    def write_annotations(*_args: object, **_kwargs: object) -> int:
        events.append("annotations")
        return 0

    client.upload_task_annotations.side_effect = write_annotations
    invalidator = Mock(
        side_effect=lambda *_args, **_kwargs: events.append("invalidate")
    )
    deps = UploadDependencies(remote, files, manifests, invalidator)
    return client, request, deps, events


def test_fresh_upload_durably_records_intent_pending_and_id_before_writes() -> None:
    """Injected manifests preserve crash-safe fresh upload checkpoint ordering."""
    client, request, deps, events = _upload_setup()

    outcome = upload_dataset(client, request, deps=deps)

    assert outcome.task_id == 42
    assert events == [
        "save-intent",
        "save-pending",
        "create",
        "save-id",
        "attach",
        "annotations",
        "invalidate",
        "save-completed",
        "delete",
    ]
    cast("Mock", deps.storage).upload.assert_not_called()


def test_failed_required_creation_checkpoint_prevents_remote_creation() -> None:
    """A failed durable creation-intent write cannot leave an ambiguous new task."""
    client, request, deps, events = _upload_setup()
    original_save = cast("Mock", deps.manifests).save.side_effect

    def fail_pending(manifest: UploadManifest, *, required: bool = False) -> None:
        original_save(manifest, required=required)
        if manifest.creation_pending:
            raise Cveta2Error("checkpoint failed")

    cast("Mock", deps.manifests).save.side_effect = fail_pending
    with pytest.raises(Cveta2Error, match="checkpoint failed"):
        upload_dataset(client, request, deps=deps)

    assert events == ["save-intent", "save-pending"]
    client.create_upload_task.assert_not_called()
    client.upload_task_annotations.assert_not_called()
    cast("Mock", deps.invalidate).assert_not_called()


def test_ambiguous_resume_stops_before_storage_or_remote_writes() -> None:
    """A pending unknown create identity cannot authorize duplicate creation."""
    from dataclasses import replace

    from cveta2.application.use_cases.upload import request_fingerprint

    client, request, deps, events = _upload_setup()
    manifest = new_manifest(
        "",
        request_fingerprint(request),
        request.project_id,
        request.task_name,
        client.detect_project_cloud_storage.return_value,
        {"a.jpg": "2026-10/a.jpg"},
        ["project/2026-10/a.jpg"],
        host=client.host,
        intent_complete=True,
        started_at="fixed",
    )
    manifest.creation_pending = True
    cast("Mock", deps.manifests).load.return_value = manifest

    with pytest.raises(Cveta2Error, match="неизвестен"):
        upload_dataset(client, replace(request, resume=True), deps=deps)

    assert events == []
    cast("Mock", deps.files).resolve_images.assert_not_called()
    cast("Mock", deps.storage).mapping.assert_not_called()
    client.create_upload_task.assert_not_called()
    cast("Mock", deps.manifests).save.assert_not_called()


@pytest.mark.parametrize("resume", [False, True])
def test_completed_manifest_cleanup_returns_outcome_without_replaying_writes(
    *,
    resume: bool,
) -> None:
    """Completed durable counts suppress all writes after failed prior cleanup."""
    from dataclasses import replace

    from cveta2.application.use_cases.upload import request_fingerprint

    client, request, deps, events = _upload_setup()
    manifest = new_manifest(
        "",
        request_fingerprint(request),
        request.project_id,
        request.task_name,
        client.detect_project_cloud_storage.return_value,
        {"a.jpg": "2026-10/a.jpg"},
        ["project/2026-10/a.jpg"],
        host=client.host,
        intent_complete=True,
        started_at="fixed",
    )
    manifest.task_id = 42
    manifest.completed_counts = (4, 2, 1)
    cast("Mock", deps.manifests).load.return_value = manifest

    outcome = upload_dataset(client, replace(request, resume=resume), deps=deps)

    assert (outcome.task_id, outcome.annotations, outcome.issues, outcome.jobs) == (
        42,
        4,
        2,
        1,
    )
    assert events == ["delete"]
    cast("Mock", deps.files).resolve_images.assert_not_called()
    cast("Mock", deps.storage).mapping.assert_not_called()
    client.detect_project_cloud_storage.assert_not_called()
    client.create_upload_task.assert_not_called()
    cast("Mock", deps.manifests).save.assert_not_called()

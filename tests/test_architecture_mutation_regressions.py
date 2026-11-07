"""Workflow-composition behaviour awaiting placement in its module test files.

Proposed homes: the sync-root tests in ``test_sync_root_override.py``, the
``resolved_task`` test in ``test_task_cache.py`` and the application-level
``build_search_dirs`` test in ``test_upload_helpers.py``.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cveta2.application.client import ApplicationClient
from cveta2.application.use_cases.upload import build_search_dirs
from cveta2.composition.workflows import apply_sync_root_override, resolved_task
from cveta2.domain.models import TaskInfo
from cveta2.domain.storage import CloudStorageInfo
from tests.helpers import write_split_config_yaml


def test_sync_root_composition_uses_selected_config_and_preserves_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chosen config and project resolve the root before pure application."""
    default_config = tmp_path / "default.yaml"
    write_split_config_yaml(default_config, project_ids={"chosen": 1}, sync_roots={"chosen": "wrong/prefix"})
    monkeypatch.setenv("CVETA2_CONFIG", str(default_config))
    selected_config = tmp_path / "selected.yaml"
    write_split_config_yaml(
        selected_config,
        project_ids={"chosen": 1, "other": 2},
        sync_roots={
            "chosen": "s3://new-bucket/nested/images",
            "other": "wrong/project",
        },
    )
    storage = CloudStorageInfo(id=7, bucket="original-bucket", prefix="old", endpoint_url="https://s3.test")

    resolved = apply_sync_root_override("chosen", storage, config_path=selected_config)

    assert resolved == CloudStorageInfo(
        id=7,
        bucket="new-bucket",
        prefix="nested/images",
        endpoint_url="https://s3.test",
    )
    assert storage.bucket == "original-bucket"
    assert storage.prefix == "old"


def test_explicit_sync_root_avoids_configuration_loading() -> None:
    """Explicit roots remain usable when configuration cannot be read."""
    storage = CloudStorageInfo(id=7, bucket="original-bucket", prefix="old", endpoint_url="https://s3.test")
    with patch(
        "cveta2.composition.workflows.SyncRootsConfig.load",
        side_effect=AssertionError("explicit roots must not load configuration"),
    ):
        resolved = apply_sync_root_override("chosen", storage, "explicit/images")

    assert resolved == CloudStorageInfo(
        id=7,
        bucket="original-bucket",
        prefix="explicit/images",
        endpoint_url="https://s3.test",
    )


def test_task_context_preserves_identity_for_exit_invalidation() -> None:
    """The selected project name must reach config-backed cache invalidation."""
    client = MagicMock(spec=ApplicationClient)
    task = TaskInfo(id=5, name="task", project_id=7, status="completed", subset="", updated_date="")
    storage = CloudStorageInfo(id=2, bucket="bucket", prefix="raw", endpoint_url="")
    client.list_project_tasks.return_value = [task]
    client.resolve_task_selectors.return_value = [task]
    client.detect_project_cloud_storage.return_value = storage
    with patch("cveta2.composition.workflows.invalidate_local_entry") as invalidate:
        with resolved_task(client, 7, "chosen", 5) as entered:
            assert entered is task
            invalidate.assert_not_called()
        invalidate.assert_called_once_with(7, 5, "chosen", storage)


@pytest.mark.parametrize("root", ["images", Path("images")])
def test_upload_search_dirs_preserves_single_root(
    root: str | Path,
) -> None:
    assert build_search_dirs(root, "chosen", cache_dir=Path("cache")) == [
        Path("images"),
        Path("cache"),
    ]

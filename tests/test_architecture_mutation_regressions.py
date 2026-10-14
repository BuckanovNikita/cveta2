"""Observe behavior at effect boundaries extracted from mutation-gated modules."""

from pathlib import Path
from threading import get_ident
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cveta2.adapters.execution.concurrency import run_concurrent
from cveta2.application.client import ApplicationClient
from cveta2.application.ports.client import ClientSettings
from cveta2.application.ports.conversion import ConversionFiles
from cveta2.application.ports.cvat import CvatApiPort
from cveta2.application.ports.dataset import DatasetFiles
from cveta2.application.ports.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawIssue,
    RawJob,
)
from cveta2.application.ports.images import ImageReadPort
from cveta2.application.use_cases.convert.coco import convert_to_coco
from cveta2.application.use_cases.convert.yolo import convert_from_yolo, convert_to_yolo
from cveta2.application.use_cases.merge import merge_datasets
from cveta2.application.use_cases.upload import build_search_dirs
from cveta2.composition.workflows import apply_sync_root_override, resolved_task
from cveta2.domain.models import TaskInfo
from cveta2.domain.storage import CloudStorageInfo
from cveta2.domain.upload import new_manifest


def test_sync_root_composition_uses_selected_config_and_preserves_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chosen config and project resolve the root before pure application."""
    default_config = tmp_path / "default.yaml"
    default_config.write_text("sync_roots:\n  chosen: wrong/prefix\n", encoding="utf-8")
    monkeypatch.setenv("CVETA2_CONFIG", str(default_config))
    selected_config = tmp_path / "selected.yaml"
    selected_config.write_text(
        "sync_roots:\n  chosen: s3://new-bucket/nested/images\n"
        "  other: wrong/project\n",
        encoding="utf-8",
    )
    storage = CloudStorageInfo(
        id=7, bucket="original-bucket", prefix="old", endpoint_url="https://s3.test"
    )

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
    storage = CloudStorageInfo(
        id=7, bucket="original-bucket", prefix="old", endpoint_url="https://s3.test"
    )
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
    task = TaskInfo(
        id=5, name="task", project_id=7, status="completed", subset="", updated_date=""
    )
    storage = CloudStorageInfo(id=2, bucket="bucket", prefix="raw", endpoint_url="")
    client.list_project_tasks.return_value = [task]
    client.resolve_task_selectors.return_value = [task]
    client.detect_project_cloud_storage.return_value = storage
    with patch("cveta2.composition.workflows.invalidate_local_entry") as invalidate:
        with resolved_task(client, 7, "chosen", 5) as entered:
            assert entered is task
            invalidate.assert_not_called()
        invalidate.assert_called_once_with(7, 5, "chosen", storage)


def test_label_usage_propagates_unexpected_failure_unchanged() -> None:
    """A non-API exception must retain its identity across execution."""
    api = MagicMock(spec=CvatApiPort)
    api.get_project_tasks.return_value = [
        TaskInfo(
            id=5,
            name="task",
            project_id=7,
            status="completed",
            subset="",
            updated_date="",
        )
    ]
    failure = ValueError("unexpected annotation failure")
    api.get_task_annotations.side_effect = failure
    client = ApplicationClient(
        ClientSettings(),
        images=MagicMock(spec=ImageReadPort),
        runner=run_concurrent,
        api=api,
    )
    with pytest.raises(ValueError, match="unexpected annotation failure") as caught:
        client.count_label_usage(7)
    assert caught.value is failure


def test_label_usage_keeps_annotation_reads_on_the_calling_thread() -> None:
    """The original sequential counting contract owns unprotected counters."""
    api = MagicMock(spec=CvatApiPort)
    api.get_project_tasks.return_value = [
        TaskInfo(
            id=5,
            name="task",
            project_id=7,
            status="completed",
            subset="",
            updated_date="",
        )
    ]
    readers: list[int] = []

    def read_annotations(_task_id: int) -> RawAnnotations:
        readers.append(get_ident())
        return RawAnnotations()

    api.get_task_annotations.side_effect = read_annotations
    client = ApplicationClient(
        ClientSettings(cvat_workers=8),
        images=MagicMock(spec=ImageReadPort),
        runner=run_concurrent,
        api=api,
    )
    assert client.count_label_usage(7) == {}
    assert readers == [get_ident()]


def test_inner_fetch_defaults_include_unfinished_tasks_and_empty_context_name() -> None:
    api = MagicMock(spec=CvatApiPort)
    task = TaskInfo(
        id=5, name="task", project_id=7, status="annotation", subset="", updated_date=""
    )
    api.get_project_tasks.return_value = [task]
    api.get_project_labels.return_value = []
    client = ApplicationClient(
        ClientSettings(),
        images=MagicMock(spec=ImageReadPort),
        runner=run_concurrent,
        api=api,
    )
    context = client.prepare_fetch(7)
    assert context.tasks == [task]
    assert context.project_name == ""


def test_inner_issue_creation_default_recreates_requested_existing_issue() -> None:
    api = MagicMock(spec=CvatApiPort)
    api.get_task_data_meta.return_value = RawDataMeta(
        frames=[RawFrame(name="a.jpg", width=100, height=100)]
    )
    api.get_task_jobs.return_value = [RawJob(id=9, start_frame=0, stop_frame=0)]
    api.get_task_issues.return_value = [
        RawIssue(id=3, frame=0, resolved=False, comments=["fix"], position=[1, 2, 3, 4])
    ]
    rows = pd.DataFrame(
        [
            {
                "image_name": "a.jpg",
                "issue_state": "new",
                "issue_text": "fix",
                "bbox_x_tl": 1,
                "bbox_y_tl": 2,
                "bbox_x_br": 3,
                "bbox_y_br": 4,
            }
        ]
    )
    client = ApplicationClient(
        ClientSettings(),
        images=MagicMock(spec=ImageReadPort),
        runner=run_concurrent,
        api=api,
    )
    assert client.create_task_issues(5, rows) == 1
    assert api.create_issue.call_args.args[0].message == "fix"
    api.get_task_issues.assert_not_called()


@pytest.mark.parametrize("format_name", ["yolo", "coco"])
def test_inner_export_default_materialization_is_auto(format_name: str) -> None:
    files = MagicMock(spec=ConversionFiles)
    files.read_dataset_csv.return_value = pd.DataFrame(
        [
            {
                "image_name": "a.jpg",
                "instance_shape": "box",
                "instance_label": "car",
                "split": "train",
                "image_width": 100,
                "image_height": 100,
                "bbox_x_tl": 10,
                "bbox_y_tl": 10,
                "bbox_x_br": 20,
                "bbox_y_br": 20,
            }
        ]
    )
    files.resolve_images.return_value = ({"a.jpg": Path("input/a.jpg")}, [])
    files.coco_owned_paths.return_value = set()
    files.resolved_output_dir.return_value = Path("output")
    export = convert_to_yolo if format_name == "yolo" else convert_to_coco
    assert export("data.csv", "output", files=files) == Path("output")
    assert files.materialize_image.call_count == 1
    assert files.materialize_image.call_args.args[2] == "auto"


def test_inner_import_default_reuses_the_first_image_dimensions() -> None:
    files = MagicMock(spec=ConversionFiles)
    files.dataset_yaml_available.return_value = False
    files.prediction_labels.return_value = [Path("a.txt"), Path("b.txt")]
    files.label_text.return_value = "0 .5 .5 .2 .2\n"
    files.find_image_by_stem.side_effect = [Path("a.jpg"), Path("b.jpg")]
    files.image_size.side_effect = [(100, 100), (200, 200)]
    assert convert_from_yolo("predictions", "output.csv", files=files) == Path(
        "output.csv"
    )
    rows = files.write_conversion_csv.call_args.args[0]
    assert [row["image_width"] for row in rows] == [100, 100]
    assert [row["image_height"] for row in rows] == [100, 100]
    assert files.image_size.call_count == 1


def test_inner_merge_default_new_rows_win_over_higher_task_ids() -> None:
    files = MagicMock(spec=DatasetFiles)
    files.read_dataset_csv.side_effect = [
        pd.DataFrame(
            [{"image_name": "same.jpg", "task_id": 9, "instance_label": "old"}]
        ),
        pd.DataFrame(
            [{"image_name": "same.jpg", "task_id": 2, "instance_label": "new"}]
        ),
    ]
    files.read_deleted_names.return_value = set()
    result = merge_datasets("old.csv", "new.csv", "out.csv", files=files)
    assert result["instance_label"].tolist() == ["new"]
    assert files.save_csv.call_args.args[0] is result
    assert files.save_csv.call_args.args[1] == Path("out.csv")


@pytest.mark.parametrize("root", ["images", Path("images")])
def test_upload_search_dirs_preserves_single_root(
    root: str | Path,
) -> None:
    assert build_search_dirs(root, "chosen", cache_dir=Path("cache")) == [
        Path("images"),
        Path("cache"),
    ]


def test_manifest_default_does_not_claim_complete_recovery_intent() -> None:
    storage = CloudStorageInfo(id=7, bucket="bucket", prefix="raw", endpoint_url="")
    manifest = new_manifest(
        "data.csv",
        "fingerprint",
        7,
        "task",
        storage,
        {"a.jpg": "raw/a.jpg"},
        ["a.jpg"],
        host="https://cvat.test",
        started_at="2026-10-14T00:00:00Z",
    )
    assert manifest.intent_complete is False

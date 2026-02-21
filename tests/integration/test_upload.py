"""Integration tests for upload (S3Uploader, create_upload_task, etc).

Requires a running, seeded CVAT + MinIO (see scripts/integration_up.sh).
Uses coco8-dev project and tests/fixtures/data/coco8/images/.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pandas as pd
import pytest

from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.client import CvatClient
from cveta2.config import CvatConfig, IgnoreConfig
from cveta2.image_downloader import CloudStorageInfo
from cveta2.image_uploader import S3Uploader, resolve_images
from tests.integration.conftest import _env, _make_sdk_client

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COCO8_IMAGES_DIR = REPO_ROOT / "tests" / "fixtures" / "data" / "coco8" / "images"

# Same image names as seed_cvat.py (flat names under bucket)
IMAGE_NAMES = [
    "000000000009.jpg",
    "000000000025.jpg",
    "000000000030.jpg",
    "000000000034.jpg",
    "000000000036.jpg",
    "000000000042.jpg",
    "000000000049.jpg",
    "000000000061.jpg",
]


def _coco8_search_dirs() -> list[Path]:
    """Directories to search for coco8 images (train + val)."""
    return [
        COCO8_IMAGES_DIR / "train",
        COCO8_IMAGES_DIR / "val",
    ]


def _get_project_and_storage() -> tuple[int, str, CloudStorageInfo, CvatConfig]:
    """Connect to CVAT, resolve coco8-dev project and cloud storage.

    Skips if unreachable.
    """
    try:
        sdk_client = _make_sdk_client()
    except (OSError, ConnectionError) as exc:
        pytest.skip(f"CVAT not reachable: {exc}")
    try:
        adapter = SdkCvatApiAdapter(sdk_client)
        projects = adapter.list_projects()
        project = next(
            (p for p in projects if p.name.strip().lower() == "coco8-dev"), None
        )
        if project is None:
            pytest.skip("coco8-dev project not found (run seed_cvat.py first)")
        host = _env("CVAT_INTEGRATION_HOST", "http://localhost:8080")
        username = _env("CVAT_INTEGRATION_USER", "admin")
        password = _env("CVAT_INTEGRATION_PASSWORD", "admin")
        cfg = CvatConfig(host=host, username=username, password=password)
        with CvatClient(cfg) as client:
            cs_info = client.detect_project_cloud_storage(project.id)
        if cs_info is None:
            pytest.skip("coco8-dev has no cloud storage (run seed_cvat.py first)")
        return project.id, project.name, cs_info, cfg
    finally:
        sdk_client.close()


def _cs_info_for_host(cs_info: CloudStorageInfo) -> CloudStorageInfo:
    """CloudStorageInfo with host-visible MinIO endpoint (for S3Uploader from host)."""
    endpoint = _env("MINIO_ENDPOINT", "http://localhost:9000")
    return CloudStorageInfo(
        id=cs_info.id,
        bucket=cs_info.bucket,
        prefix=cs_info.prefix,
        endpoint_url=endpoint,
    )


class TestS3UploaderIntegration:
    """S3Uploader against real MinIO (host endpoint)."""

    def test_upload_or_skip_existing(self) -> None:
        _project_id, _project_name, cs_info, _cfg = _get_project_and_storage()
        search_dirs = _coco8_search_dirs()
        if not any(d.is_dir() for d in search_dirs):
            pytest.skip("coco8 images dirs missing (run integration_up.sh to download)")
        names = set(IMAGE_NAMES[:3])
        found, _missing = resolve_images(names, search_dirs)
        if not found:
            pytest.skip("No coco8 images found on disk")
        cs_host = _cs_info_for_host(cs_info)
        stats = S3Uploader().upload(cs_host, found)
        assert stats.total == len(found)
        assert stats.failed == 0
        assert stats.uploaded + stats.skipped_existing == stats.total


class TestCreateUploadTaskIntegration:
    """create_upload_task against real CVAT + MinIO."""

    def test_create_upload_task(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        image_names = IMAGE_NAMES[:2]
        with CvatClient(cfg) as client:
            task_id = client.create_upload_task(
                project_id=project_id,
                name="integration-upload-test",
                image_names=image_names,
                cloud_storage_id=cs_info.id,
                segment_size=2,
            )
        assert task_id > 0
        sdk_client = _make_sdk_client()
        try:
            task = sdk_client.tasks.retrieve(task_id)
            assert task.size == len(image_names)
        finally:
            sdk_client.close()


class TestUploadTaskAnnotationsIntegration:
    """upload_task_annotations: upload bbox DataFrame and verify via API."""

    def test_upload_task_annotations(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        image_names = IMAGE_NAMES[:1]
        with CvatClient(cfg) as client:
            task_id = client.create_upload_task(
                project_id=project_id,
                name="integration-annot-test",
                image_names=image_names,
                cloud_storage_id=cs_info.id,
                segment_size=10,
            )
            ann_df = pd.DataFrame(
                [
                    {
                        "image_name": image_names[0],
                        "instance_label": "person",
                        "bbox_x_tl": 10.0,
                        "bbox_y_tl": 20.0,
                        "bbox_x_br": 110.0,
                        "bbox_y_br": 120.0,
                    }
                ]
            )
            num_shapes = client.upload_task_annotations(
                task_id=task_id, annotations_df=ann_df
            )
        assert num_shapes == 1
        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            annotations = adapter.get_task_annotations(task_id)
            assert len(annotations.shapes) == 1
            shape = annotations.shapes[0]
            assert shape.type == "rectangle"
            assert shape.points == [10.0, 20.0, 110.0, 120.0]
        finally:
            sdk_client.close()


class TestFullUploadFlowIntegration:
    """Full flow: create task, upload annotations, fetch and verify."""

    def test_full_upload_flow(self) -> None:
        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        image_names = IMAGE_NAMES[:2]
        with CvatClient(cfg) as client:
            task_id = client.create_upload_task(
                project_id=project_id,
                name="integration-full-flow-test",
                image_names=image_names,
                cloud_storage_id=cs_info.id,
                segment_size=10,
            )
            ann_df = pd.DataFrame(
                [
                    {
                        "image_name": image_names[0],
                        "instance_label": "person",
                        "bbox_x_tl": 0.0,
                        "bbox_y_tl": 0.0,
                        "bbox_x_br": 100.0,
                        "bbox_y_br": 100.0,
                    },
                    {
                        "image_name": image_names[1],
                        "instance_label": "car",
                        "bbox_x_tl": 50.0,
                        "bbox_y_tl": 50.0,
                        "bbox_x_br": 150.0,
                        "bbox_y_br": 150.0,
                    },
                ]
            )
            num_shapes = client.upload_task_annotations(
                task_id=task_id, annotations_df=ann_df
            )
        assert num_shapes == 2
        sdk_client = _make_sdk_client()
        try:
            adapter = SdkCvatApiAdapter(sdk_client)
            annotations = adapter.get_task_annotations(task_id)
            assert len(annotations.shapes) == 2
            labels = {s.label_id: s for s in annotations.shapes}
            assert len(labels) == 2
        finally:
            sdk_client.close()


def _normalize_bbox_df(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to bbox rows and sort for stable comparison."""
    if df.empty:
        return df
    has_shape = "instance_shape" in df.columns
    bbox = df[df["instance_shape"] == "box"].copy() if has_shape else df.copy()
    cols = [
        "image_name",
        "instance_label",
        "bbox_x_tl",
        "bbox_y_tl",
        "bbox_x_br",
        "bbox_y_br",
    ]
    cols = [c for c in cols if c in bbox.columns]
    if not cols:
        return cast("pd.DataFrame", bbox)
    bbox = bbox.sort_values(by=cols).reset_index(drop=True)
    if set(cols).issubset(bbox.columns):
        return cast("pd.DataFrame", bbox[cols])
    return cast("pd.DataFrame", bbox)


class TestUploadThenFetchTaskIntegration:
    """Upload a task, run cveta2 fetch-task, compare results are equal."""

    def test_upload_task_then_fetch_task_results_equal(self, tmp_path: Path) -> None:
        from cveta2.commands.fetch import run_fetch_task

        project_id, _project_name, cs_info, cfg = _get_project_and_storage()
        task_name = "upload-then-fetch-test"
        image_names = IMAGE_NAMES[:2]
        uploaded_anns = pd.DataFrame(
            [
                {
                    "image_name": image_names[0],
                    "instance_label": "person",
                    "bbox_x_tl": 5.0,
                    "bbox_y_tl": 10.0,
                    "bbox_x_br": 105.0,
                    "bbox_y_br": 110.0,
                },
                {
                    "image_name": image_names[1],
                    "instance_label": "car",
                    "bbox_x_tl": 50.0,
                    "bbox_y_tl": 60.0,
                    "bbox_x_br": 200.0,
                    "bbox_y_br": 180.0,
                },
            ]
        )
        with CvatClient(cfg) as client:
            task_id = client.create_upload_task(
                project_id=project_id,
                name=task_name,
                image_names=image_names,
                cloud_storage_id=cs_info.id,
                segment_size=10,
            )
            client.upload_task_annotations(
                task_id=task_id, annotations_df=uploaded_anns
            )
        out_dir = tmp_path / "fetch_out"
        args = argparse.Namespace(
            project=str(project_id),
            task=[task_name],
            output_dir=str(out_dir),
            completed_only=False,
            no_images=True,
            images_dir=None,
            save_tasks=False,
        )
        with (
            patch("cveta2.commands.fetch.load_config", return_value=cfg),
            patch("cveta2.commands.fetch.require_host"),
            patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
            patch(
                "cveta2.commands.fetch.load_ignore_config",
                return_value=IgnoreConfig(),
            ),
            patch(
                "cveta2.client.CvatClient.detect_project_cloud_storage",
                return_value=cs_info,
            ),
        ):
            run_fetch_task(args)
        dataset_csv = out_dir / "dataset.csv"
        in_progress_csv = out_dir / "in_progress.csv"
        if in_progress_csv.exists():
            fetched_df = pd.read_csv(in_progress_csv)
        else:
            assert dataset_csv.exists(), "expected dataset.csv or in_progress.csv"
            fetched_df = pd.read_csv(dataset_csv)
        uploaded_norm = _normalize_bbox_df(uploaded_anns)
        fetched_norm = _normalize_bbox_df(fetched_df)
        assert len(fetched_norm) == len(uploaded_norm), (
            f"row count: uploaded {len(uploaded_norm)} vs fetched {len(fetched_norm)}"
        )
        for col in [
            "image_name",
            "instance_label",
            "bbox_x_tl",
            "bbox_y_tl",
            "bbox_x_br",
            "bbox_y_br",
        ]:
            if col not in fetched_norm.columns or col not in uploaded_norm.columns:
                continue
            for i, (u, f) in enumerate(
                zip(uploaded_norm[col], fetched_norm[col], strict=True)
            ):
                if isinstance(u, (int, float)) and isinstance(f, (int, float)):
                    assert abs(float(u) - float(f)) < 1e-5, (
                        f"row {i} {col}: uploaded {u} vs fetched {f}"
                    )
                else:
                    assert u == f, f"row {i} {col}: uploaded {u!r} vs fetched {f!r}"

"""Shared builder helpers for cveta2 tests.

Plain importable functions and constants (no pytest fixtures — those live
in ``tests/conftest.py``).  Every builder returns fully-typed objects with
sensible defaults; override only what the test cares about.
"""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Final
from unittest.mock import MagicMock

import pandas as pd
import yaml

from cveta2._client.dtos import RawShape
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.image_downloader import CloudStorageInfo
from cveta2.models import CSV_COLUMNS, BBoxAnnotation, DeletedImage, TaskInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import (
    FakeProjectConfig,
    build_fake_project,
    task_indices_by_names,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from tests.fixtures.fake_cvat_project import LoadedFixtures

CFG: Final = CvatConfig(
    host="http://fake-cvat", username="test-user", password="test-password"
)


def build_fake(
    base: LoadedFixtures,
    task_names: list[str],
    statuses: list[str] | None = None,
    **kwargs: Any,
) -> LoadedFixtures:
    """Build a fake project from named base tasks with optional statuses."""
    indices = task_indices_by_names(base.tasks, task_names)
    config = FakeProjectConfig(
        task_indices=indices,
        task_statuses=statuses if statuses is not None else "keep",
        **kwargs,
    )
    return build_fake_project(base, config)


def make_fake_client(fixtures: LoadedFixtures) -> CvatClient:
    """Create a CvatClient backed by fake API data."""
    return CvatClient(CvatConfig(), api=FakeCvatApi(fixtures))


def client_with_api(api: Any) -> CvatClient:
    """Wrap an injected API port (real or mock) in a CvatClient."""
    return CvatClient(CFG, api=api)


def write_test_config(
    path: Path,
    *,
    image_cache: dict[str, str] | None = None,
) -> None:
    """Write a minimal config YAML for testing."""
    data: dict[str, object] = {
        "cvat": {
            "host": "http://localhost:8080",
            "username": "test-user",
            "password": "test-password",
        },
    }
    if image_cache:
        data["image_cache"] = image_cache
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def make_bbox(**overrides: Any) -> BBoxAnnotation:
    """Create a BBoxAnnotation with sensible defaults."""
    defaults: dict[str, Any] = {
        "image_name": "img.jpg",
        "image_width": 640,
        "image_height": 480,
        "instance_label": "car",
        "bbox_x_tl": 10.0,
        "bbox_y_tl": 20.0,
        "bbox_x_br": 100.0,
        "bbox_y_br": 200.0,
        "task_id": 1,
        "task_name": "task-1",
        "task_status": "completed",
        "task_updated_date": "2026-01-01T00:00:00",
        "created_by_username": "tester",
        "frame_id": 0,
        "subset": "train",
        "occluded": False,
        "z_order": 0,
        "rotation": 0.0,
        "source": "manual",
        "annotation_id": 42,
        "attributes": {"color": "red"},
    }
    defaults.update(overrides)
    return BBoxAnnotation(**defaults)


def make_task(
    task_id: int = 1,
    *,
    name: str | None = None,
    status: str = "completed",
    subset: str = "",
    updated: str = "2026-01-01T00:00:00+00:00",
) -> TaskInfo:
    """Create a TaskInfo with test defaults."""
    return TaskInfo(
        id=task_id,
        name=name if name is not None else f"task-{task_id}",
        status=status,
        subset=subset,
        updated_date=updated,
    )


def make_deleted(
    image: str,
    task_id: int,
    updated: str,
    status: str = "completed",
) -> DeletedImage:
    """Create a DeletedImage record with test defaults."""
    return DeletedImage(
        task_id=task_id,
        task_name=f"task-{task_id}",
        task_status=status,
        task_updated_date=updated,
        frame_id=0,
        image_name=image,
    )


_RAW_SHAPE_DEFAULTS: Final[dict[str, Any]] = {
    "id": 1,
    "type": "rectangle",
    "frame": 0,
    "label_id": 1,
    "points": [10.0, 20.0, 100.0, 200.0],
    "occluded": False,
    "z_order": 0,
    "rotation": 0.0,
    "source": "manual",
    "attributes": [],
    "created_by": "tester",
}


def make_raw_shape(**overrides: Any) -> RawShape:
    """Create a RawShape DTO with rectangle defaults."""
    return RawShape(**{**_RAW_SHAPE_DEFAULTS, **overrides})


def make_sdk_shape(**overrides: object) -> SimpleNamespace:
    """Create an SDK-shaped object (as returned by cvat_sdk) for adapter tests."""
    defaults: dict[str, object] = {
        "id": 1,
        "type": SimpleNamespace(value="rectangle"),
        "frame": 0,
        "label_id": 10,
        "points": [1.0, 2.0, 3.0, 4.0],
        "occluded": False,
        "z_order": 0,
        "rotation": 0.0,
        "source": "manual",
        "attributes": [],
        "created_by": None,
        "owner": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_cs_info(
    *,
    cs_id: int = 1,
    bucket: str = "test-bucket",
    prefix: str = "images",
    endpoint_url: str = "http://localhost:9000",
) -> CloudStorageInfo:
    """Create a CloudStorageInfo with test defaults."""
    return CloudStorageInfo(
        id=cs_id,
        bucket=bucket,
        prefix=prefix,
        endpoint_url=endpoint_url,
    )


def csv_row(  # noqa: PLR0913
    image: str = "a.jpg",
    *,
    shape: str = "box",
    label: str | None = "cat",
    split: str | None = None,
    task_id: int = 1,
    status: str = "completed",
    updated: str = "2026-01-01T00:00:00Z",
    **overrides: object,
) -> dict[str, object]:
    """Build a full-``CSV_COLUMNS`` annotation row dict.

    ``shape="box"`` fills default bbox coordinates; ``shape="none"``
    leaves bbox columns (and the label) as ``None``.  Any column can be
    overridden via keyword arguments.
    """
    row: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
    row["image_name"] = image
    row["image_width"] = 640
    row["image_height"] = 480
    row["instance_shape"] = shape
    row["instance_label"] = label if shape != "none" else None
    row["task_id"] = task_id
    row["task_name"] = f"task-{task_id}"
    row["task_status"] = status
    row["task_updated_date"] = updated
    row["frame_id"] = 0
    row["split"] = split
    row["subset"] = ""
    row["source"] = "manual"
    row["attributes"] = json.dumps({})
    if shape == "box":
        row["bbox_x_tl"] = 10.0
        row["bbox_y_tl"] = 20.0
        row["bbox_x_br"] = 100.0
        row["bbox_y_br"] = 200.0
        row["created_by_username"] = "admin"
        row["occluded"] = False
        row["z_order"] = 0
        row["rotation"] = 0.0
        row["annotation_id"] = 1
    row.update(overrides)
    return row


def make_df(
    rows: list[dict[str, object]],
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Build a DataFrame from row dicts; *columns* keeps empty frames typed."""
    if not rows:
        return pd.DataFrame(columns=list(columns) if columns else list(CSV_COLUMNS))
    if columns:
        return pd.DataFrame(rows, columns=list(columns))
    return pd.DataFrame(rows)


def write_dataset_csv(
    path: Path,
    rows: list[dict[str, object]],
    *,
    columns: Sequence[str] | None = None,
) -> Path:
    """Write row dicts to *path* as a UTF-8 CSV and return the path."""
    df = pd.DataFrame(rows, columns=list(columns) if columns else None)
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def make_args(**kwargs: object) -> argparse.Namespace:
    """Build an argparse.Namespace from keyword arguments."""
    return argparse.Namespace(**kwargs)


def make_fetch_args(**overrides: object) -> argparse.Namespace:
    """Build a Namespace mimicking parsed ``fetch-task`` CLI args."""
    defaults: dict[str, object] = {
        "project": "1",
        "task": None,
        "output_dir": "out",
        "completed_only": False,
        "no_images": True,
        "images_dir": None,
        "save_tasks": False,
        "no_cache": True,
        "force": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def mock_client_ctx(*, project_id: int = 1) -> MagicMock:
    """Build a MagicMock CvatClient usable as a context manager."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.resolve_project_id.return_value = project_id
    return client

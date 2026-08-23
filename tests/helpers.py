"""Shared builder helpers for cveta2 tests.

Plain importable functions and constants (no pytest fixtures — those live
in ``tests/conftest.py``).  Every builder returns fully-typed objects with
sensible defaults; override only what the test cares about.
"""

from __future__ import annotations

import argparse
import json
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Final
from unittest.mock import MagicMock, patch

import pandas as pd
import yaml

import cveta2
from cveta2._client.dtos import RawShape
from cveta2.cli import CliApp
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.image_downloader import CloudStorageInfo
from cveta2.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
    TaskAnnotations,
    TaskInfo,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi, job_position_for_status
from tests.fixtures.fake_cvat_project import (
    FakeProjectConfig,
    build_fake_project,
    task_indices_by_names,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    import pytest

    from tests.fixtures.fake_cvat_project import LoadedFixtures
    from tests.fixtures.fake_s3 import FakeS3Client

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


def fake_connection(fixtures: LoadedFixtures) -> cveta2.Connection:
    """Build an API ``Connection`` around a fake-backed client."""
    return cveta2.Connection(client=make_fake_client(fixtures))


def client_with_api(api: Any) -> CvatClient:
    """Wrap an injected API port (real or mock) in a CvatClient."""
    return CvatClient(CFG, api=api)


def parse_cli_args(*argv: str) -> argparse.Namespace:
    """Parse argv with the real CLI parser so test args match its defaults."""
    return CliApp()._parser.parse_args(list(argv))


@contextmanager
def patch_cli_client(
    client: Any | None = None,
    *,
    factory: Callable[..., Any] | None = None,
    cached_projects: Sequence[Any] = (),
    config: CvatConfig | None = None,
) -> Iterator[Any]:
    """Patch the CLI bootstrap seam: CvatClient constructor + projects cache.

    *client* (default: a fresh ``mock_client_ctx()``) is returned by the
    patched constructor; *factory* replaces the constructor instead (for
    FakeCvatApi-backed clients).  With *config* set, ``CvatConfig.load``
    and ``require_host`` are stubbed too, so no config file is needed.
    Yields the client (``None`` when *factory* is used).
    """
    if client is None and factory is None:
        client = mock_client_ctx()
    with ExitStack() as stack:
        if factory is not None:
            stack.enter_context(
                patch("cveta2.commands._bootstrap.CvatClient", side_effect=factory)
            )
        else:
            stack.enter_context(
                patch("cveta2.commands._bootstrap.CvatClient", return_value=client)
            )
        stack.enter_context(
            patch(
                "cveta2.commands._helpers.load_projects_cache",
                return_value=list(cached_projects),
            )
        )
        if config is not None:
            stack.enter_context(
                patch("cveta2.commands._bootstrap.CvatConfig.load", return_value=config)
            )
            stack.enter_context(patch("cveta2.commands._bootstrap.require_host"))
        yield client


def fetch_all_annotations(
    client: CvatClient,
    project_id: int,
    **kwargs: Any,
) -> ProjectAnnotations:
    """Fetch a whole project in-memory via the production per-task pipeline.

    Mirrors what ``services.fetch`` does (``prepare_fetch`` +
    ``fetch_one_task`` per task) without CSV output or the cache.
    """
    ctx = client.prepare_fetch(project_id, **kwargs)
    results: list[TaskAnnotations] = []
    for task in ctx.tasks:
        fetched = client.fetch_one_task(client.api, task, ctx)
        if fetched is not None:
            results.append(fetched)
    return TaskAnnotations.merge(results)


def split_records(
    result: ProjectAnnotations,
) -> tuple[list[BBoxAnnotation], list[ImageWithoutAnnotations]]:
    """Partition fetched annotations into (bbox, without-annotation) records."""
    bbox = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    without = [a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)]
    return bbox, without


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


def write_config_yaml(path: Path, **sections: object) -> Path:
    """Write a config YAML with the given top-level sections."""
    path.write_text(yaml.safe_dump(sections), encoding="utf-8")
    return path


def make_image(path: Path, width: int = 640, height: int = 480) -> Path:
    """Create a real RGB image file for conversion tests."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height)).save(path)
    return path


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
        "job_stage": "acceptance",
        "job_state": "completed",
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
    stage, state = job_position_for_status(status)
    return DeletedImage(
        task_id=task_id,
        task_name=f"task-{task_id}",
        job_stage=stage,
        job_state=state,
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
    row["job_stage"], row["job_state"] = job_position_for_status(status)
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


def write_convert_csv(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    """Write a `dataset.csv` with the canonical column order, for convert tests."""
    return write_dataset_csv(tmp_path / "dataset.csv", rows, columns=CSV_COLUMNS)


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


class RecordingS3Factory:
    """``make_s3_client`` stand-in that records the endpoint it was given."""

    def __init__(self, client: FakeS3Client) -> None:
        """Store *client* to hand out, and an empty endpoint log."""
        self._client = client
        self.endpoints: list[str | None] = []

    def __call__(self, endpoint_url: str | None = None) -> FakeS3Client:
        """Record *endpoint_url* and return the fixed fake client."""
        self.endpoints.append(endpoint_url)
        return self._client


def patch_recording_s3(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    fake_s3: FakeS3Client,
) -> RecordingS3Factory:
    """Route *target*'s ``make_s3_client`` to an endpoint-recording factory.

    *target* is the module whose ``make_s3_client`` name is replaced —
    the downloader and the uploader each bind their own.
    """
    factory = RecordingS3Factory(fake_s3)
    monkeypatch.setattr(f"{target}.make_s3_client", factory)
    return factory

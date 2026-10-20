"""Explicit reviewed bundle publication against this run's ClearML and MinIO.

Registry HTTP and image/source fixtures are local. ClearML projects use the exact
run tag and are removed by the session fixture; the seeded MinIO bucket is read
only and remains owned by the normal integration lifecycle.
"""

import json
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from loguru import logger
from PIL import Image

from cveta2.application.ports.dataset_bundle import BundleServices
from cveta2.application.use_cases.dataset_bundle import prepare_dataset, upload_dataset
from cveta2.composition.dataset_bundle import bundle_services
from cveta2.domain.bundle.models import UploadError
from cveta2.domain.bundle.preparation import PAYLOAD_NAMES, SOURCE_NAMES, PrepareOptions
from tests.integration.clearml_run import (
    RunError,
    RunSettings,
    delete_run_projects,
    open_session,
    project_name,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def clearml_run() -> Iterator[RunSettings]:
    """Keep every remote project under this run's exact cleanup ownership."""
    try:
        settings = RunSettings.from_env()
    except RunError as exc:
        pytest.fail(str(exc))
    try:
        import clearml  # noqa: F401
    except ImportError:
        pytest.fail("Run scripts/integration_test.sh to install the ClearML extra")
    try:
        yield settings
    finally:
        deleted = delete_run_projects(open_session(), settings.tag)
        logger.info(f"Removed {len(deleted)} ClearML projects of run {settings.tag!r}")


@pytest.fixture
def class_api() -> Iterator[str]:
    """Serve a public registry with stable class number independent of its ID."""
    payload = json.dumps(
        [
            {
                "id": 123,
                "number": 7,
                "name": "cat",
                "techClass": False,
                "isPeriodical": False,
                "isCritical": False,
                "threshold": 0.5,
            }
        ]
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert self.headers.get("Authorization") is None
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/classes"
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        assert not worker.is_alive()


@dataclass(frozen=True)
class Scenario:
    """Real remote adapters and immutable local source evidence for one dataset."""

    source: Path
    options: PrepareOptions
    services: BundleServices


@pytest.fixture
def scenario(
    tmp_path: Path,
    clearml_run: RunSettings,
    class_api: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Scenario:
    """Use local images and the already-seeded run bucket as independent roots."""
    # boto3 honors this endpoint when ClearML passes endpoint_url=None for a
    # normal s3://bucket URI. Keep credentials in environment, never metadata.
    for target, source_env in (
        ("AWS_ENDPOINT_URL_S3", "MINIO_ENDPOINT"),
        ("AWS_ACCESS_KEY_ID", "MINIO_ACCESS_KEY"),
        ("AWS_SECRET_ACCESS_KEY", "MINIO_SECRET_KEY"),
        ("AWS_DEFAULT_REGION", "MINIO_REGION"),
    ):
        monkeypatch.setenv(target, os.environ[source_env])
    bucket = os.environ["MINIO_BUCKET"]
    assert bucket == clearml_run.tag
    source = tmp_path / "source"
    images = tmp_path / "images"
    source.mkdir()
    images.mkdir()
    rows: list[dict[str, object]] = []
    for task_id, split in enumerate(("train", "val"), start=1):
        name = f"{split}.png"
        Image.new("RGB", (32, 32)).save(images / name)
        rows.append(
            {
                "image_name": name,
                "image_path": str(images / name),
                "split": split,
                "instance_label": "cat",
                "bbox_x_tl": "1",
                "bbox_y_tl": "1",
                "bbox_x_br": "20",
                "bbox_y_br": "20",
                "task_id": task_id,
                "task_completed": True,
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(source / "dataset.csv", index=False)
    for name in SOURCE_NAMES[1:]:
        frame.iloc[:0].to_csv(source / name, index=False)
    options = PrepareOptions(
        project=project_name(clearml_run.tag, "clearml-bundle"),
        dataset_name=f"{clearml_run.tag}-ds-{uuid4().hex[:8]}",
        api_url=class_api,
        local_roots=(str(images),),
        s3_roots=(f"s3://{bucket}",),
        accept_default_classes=True,
    )
    return Scenario(source, options, bundle_services())


def _source_bytes(source: Path) -> dict[str, bytes]:
    return {name: (source / name).read_bytes() for name in SOURCE_NAMES}


def test_publish_finalized_exact_payload_and_preserve_parent(
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    """Publish twice; the child inherits lineage while replacing its file manifest."""
    from clearml import Dataset

    source, options, services = scenario.source, scenario.options, scenario.services
    original = _source_bytes(source)
    prepared = tmp_path / "prepared-first"
    assert prepare_dataset(source, prepared, options, services).ready
    assert services.datasets.latest(options.project, options.dataset_name or "") is None
    first = upload_dataset(prepared, services)
    parent = Dataset.get(dataset_id=first.dataset_id)
    assert parent.is_final()
    assert set(parent.list_files()) == set(PAYLOAD_NAMES)
    parent_directory = Path(parent.get_local_copy(use_soft_links=False))
    parent_bytes = {
        name: (parent_directory / name).read_bytes() for name in PAYLOAD_NAMES
    }
    assert parent_bytes == {
        name: (prepared / name).read_bytes() for name in PAYLOAD_NAMES
    }
    assert _source_bytes(source) == original

    second_directory = tmp_path / "prepared-second"
    assert prepare_dataset(source, second_directory, options, services).ready
    second = upload_dataset(second_directory, services)
    assert second.dataset_id != first.dataset_id
    child = Dataset.get(dataset_id=second.dataset_id)
    assert child.is_final()
    assert child.get_dependency_graph()[child.id] == [parent.id]
    assert set(child.list_files()) == set(PAYLOAD_NAMES)
    child_directory = Path(child.get_local_copy(use_soft_links=False))
    assert {name: (child_directory / name).read_bytes() for name in PAYLOAD_NAMES} == {
        name: (second_directory / name).read_bytes() for name in PAYLOAD_NAMES
    }
    refreshed_parent = Dataset.get(dataset_id=parent.id)
    assert refreshed_parent.is_final()
    assert set(refreshed_parent.list_files()) == set(PAYLOAD_NAMES)
    refreshed_directory = Path(refreshed_parent.get_local_copy(use_soft_links=False))
    assert {
        name: (refreshed_directory / name).read_bytes() for name in PAYLOAD_NAMES
    } == parent_bytes
    assert _source_bytes(source) == original


def test_tampered_bundle_and_new_parent_create_no_remote_child(
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    """Rejected review evidence must never create a remote child."""
    from clearml import Dataset

    source, options, services = scenario.source, scenario.options, scenario.services

    def remote_ids() -> set[str]:
        return {
            str(item["id"])
            for item in Dataset.list_datasets(
                dataset_project=options.project,
                only_completed=False,
                recursive_project_search=False,
                include_archived=True,
            )
        }

    tampered = tmp_path / "tampered"
    assert prepare_dataset(source, tampered, options, services).ready
    before = remote_ids()
    with (tampered / "tasks.yaml").open("a", encoding="utf-8") as stream:
        stream.write("\n# changed after review\n")
    with pytest.raises(UploadError, match=r"changed|hash|измен"):
        upload_dataset(tampered, services)
    assert remote_ids() == before

    reviewed = tmp_path / "reviewed"
    competing = tmp_path / "competing"
    assert prepare_dataset(source, reviewed, options, services).ready
    assert prepare_dataset(source, competing, options, services).ready
    newer = upload_dataset(competing, services)
    before = remote_ids()
    assert newer.dataset_id in before
    with pytest.raises(UploadError, match="parent"):
        upload_dataset(reviewed, services)
    assert remote_ids() == before

#!/usr/bin/env python3
"""Seed a fresh CVAT instance with coco8-dev test data.

Reads the JSON fixture files from tests/fixtures/cvat/coco8-dev/ and
recreates the same project/task structure in a live CVAT instance.
Images are uploaded from tests/fixtures/data/coco8/images/.

Environment variables (defaults match tests/integration/.env):
  CVAT_INTEGRATION_HOST  (default http://localhost:8080)
  DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_PASSWORD  (default admin/admin)
  MINIO_ENDPOINT  (default http://localhost:9000)
  MINIO_ROOT_USER / MINIO_ROOT_PASSWORD  (default minioadmin)
  MINIO_BUCKET  (default cveta2-test)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

if TYPE_CHECKING:
    from cvat_sdk.core.client import Client as CvatClient

import boto3
from botocore.config import Config as BotoConfig
from cvat_sdk import make_client
from cvat_sdk.api_client import models as cvat_models
from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
from cvat_sdk.core.proxies.tasks import ResourceType
from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "cvat" / "coco8-dev"
IMAGES_DIR = REPO_ROOT / "tests" / "fixtures" / "data" / "coco8" / "images"
SEEDED_FILE = Path(__file__).resolve().parent / ".seeded"

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


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def _collect_image_paths() -> list[str]:
    """Return absolute paths to the 8 coco8 images (train + val)."""
    paths: list[str] = []
    for sub in ("train", "val"):
        d = IMAGES_DIR / sub
        if not d.is_dir():
            logger.error(f"Missing images directory: {d}")
            logger.error("Run scripts/integration_up.sh to download coco8 images")
            sys.exit(1)
        paths.extend(
            str(p)
            for p in sorted(d.iterdir())
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
    return paths


def _upload_images_to_minio(
    endpoint: str, access_key: str, secret_key: str, bucket: str
) -> None:
    """Upload coco8 images to MinIO bucket."""
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )

    from botocore.exceptions import ClientError

    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        s3.create_bucket(Bucket=bucket)
        logger.info(f"Created MinIO bucket: {bucket}")

    for sub in ("train", "val"):
        d = IMAGES_DIR / sub
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                s3.upload_file(str(p), bucket, p.name)

    logger.info(f"Uploaded images to s3://{bucket}/")


def _register_cloud_storage(
    client: CvatClient,
    bucket: str,
    minio_endpoint_for_cvat: str,
    access_key: str,
    secret_key: str,
) -> int:
    """Register MinIO as cloud storage in CVAT. Returns cloud_storage_id."""
    api = client.api_client.cloudstorages_api

    specific_attributes = urlencode(
        {
            "endpoint_url": minio_endpoint_for_cvat,
            "region_name": "us-east-1",
        }
    )

    cs_spec = cvat_models.CloudStorageWriteRequest(
        display_name="cveta2-test-minio",
        provider_type=cvat_models.ProviderTypeEnum("AWS_S3_BUCKET"),
        resource=bucket,
        credentials_type=cvat_models.CredentialsTypeEnum("KEY_SECRET_KEY_PAIR"),
        key=access_key,
        secret_key=secret_key,
        specific_attributes=specific_attributes,
    )
    # OPA may not have loaded auth rules yet right after CVAT starts
    for attempt in range(10):
        try:
            cs, _ = api.create(cs_spec)
            break
        except Exception:
            if attempt == 9:
                raise
            logger.warning(
                f"Cloud storage creation failed (attempt {attempt + 1}/10),"
                " retrying in 5s..."
            )
            time.sleep(5)
    logger.info(f"Registered cloud storage: id={cs.id}, bucket={bucket}")
    return int(cs.id)


def _load_project_labels() -> list[dict[str, Any]]:
    """Load label definitions from project.json fixture."""
    project_file = FIXTURES_DIR / "project.json"
    data = json.loads(project_file.read_text(encoding="utf-8"))
    return list(data.get("labels", []))


def _load_task_fixtures() -> list[dict[str, Any]]:
    """Load all task fixture files, sorted by filename."""
    tasks_dir = FIXTURES_DIR / "tasks"
    fixtures: list[dict[str, Any]] = []
    for path in sorted(tasks_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        fixtures.append(data)
    return fixtures


def _create_project(
    client: CvatClient, labels: list[dict[str, Any]], cloud_storage_id: int
) -> Any:  # noqa: ANN401
    """Create coco8-dev project with labels and cloud storage source."""
    project_spec = {
        "name": "coco8-dev",
        "labels": [{"name": lbl["name"]} for lbl in labels],
        "source_storage": {
            "location": "cloud_storage",
            "cloud_storage_id": cloud_storage_id,
        },
        "target_storage": {
            "location": "cloud_storage",
            "cloud_storage_id": cloud_storage_id,
        },
    }
    project = client.projects.create(project_spec)
    logger.info(f"Created project: {project.name} (id={project.id})")
    return project


def _build_label_id_map(
    fixture_labels: list[dict[str, Any]],
    real_labels: list[Any],
) -> dict[int, int]:
    """Map fixture label IDs to real CVAT label IDs by name."""
    real_by_name = {lbl.name: lbl.id for lbl in real_labels}
    mapping: dict[int, int] = {}
    for fl in fixture_labels:
        real_id = real_by_name.get(fl["name"])
        if real_id is not None:
            mapping[fl["id"]] = real_id
    return mapping


def _create_task(
    client: CvatClient,
    project_id: int,
    task_fixture: dict[str, Any],
    label_id_map: dict[int, int],
    cloud_storage_id: int,
) -> int:
    """Create a single task, upload annotations, delete frames. Returns task_id."""
    task_meta = task_fixture["task"]
    task_name = task_meta["name"]

    image_keys = list(IMAGE_NAMES)

    task_spec = {
        "name": task_name,
        "project_id": project_id,
        "labels": [],
    }
    task = client.tasks.create_from_data(
        spec=task_spec,
        resource_type=ResourceType.SHARE,
        resources=image_keys,
        data_params={
            "cloud_storage_id": cloud_storage_id,
            "sorting_method": "natural",
        },
    )
    logger.info(f"Created task: {task_name} (id={task.id})")

    annotations_data = task_fixture.get("annotations", {})
    shapes_raw = annotations_data.get("shapes", [])

    if shapes_raw:
        shapes = []
        for s in shapes_raw:
            new_label_id = label_id_map.get(s["label_id"])
            if new_label_id is None:
                continue
            shapes.append(
                cvat_models.LabeledShapeRequest(
                    type=cvat_models.ShapeType(s["type"]),
                    frame=s["frame"],
                    label_id=new_label_id,
                    points=s["points"],
                    occluded=s.get("occluded", False),
                    z_order=s.get("z_order", 0),
                    rotation=s.get("rotation", 0.0),
                    source=s.get("source", "manual"),
                )
            )
        if shapes:
            task.update_annotations(
                cvat_models.PatchedLabeledDataRequest(shapes=shapes),
                action=AnnotationUpdateAction.CREATE,
            )
            logger.info(f"  Uploaded {len(shapes)} shapes to task {task.id}")

    deleted_frames = task_fixture.get("data_meta", {}).get("deleted_frames", [])
    if deleted_frames:
        tasks_api = client.api_client.tasks_api
        data_meta, _ = tasks_api.retrieve_data_meta(task.id)
        current_deleted = set(data_meta.deleted_frames or [])
        new_deleted = sorted(current_deleted | set(deleted_frames))
        tasks_api.partial_update_data_meta(
            task.id,
            patched_data_meta_write_request=cvat_models.PatchedDataMetaWriteRequest(
                deleted_frames=new_deleted,
            ),
        )
        logger.info(f"  Deleted frames {deleted_frames} in task {task.id}")

    return int(task.id)


def main() -> None:
    host = _env("CVAT_INTEGRATION_HOST", "http://localhost:8080")
    username = _env("DJANGO_SUPERUSER_USERNAME", "admin")
    password = _env("DJANGO_SUPERUSER_PASSWORD", "admin")
    minio_endpoint = _env("MINIO_ENDPOINT", "http://localhost:9000")
    minio_access_key = _env("MINIO_ROOT_USER", "minioadmin")
    minio_secret_key = _env("MINIO_ROOT_PASSWORD", "minioadmin")
    minio_bucket = _env("MINIO_BUCKET", "cveta2-test")

    # MinIO endpoint as seen from inside Docker network
    minio_internal = "http://cveta2-minio:9000"

    logger.info(f"CVAT host: {host}")
    logger.info(f"MinIO endpoint: {minio_endpoint}")

    # Upload images to MinIO
    _upload_images_to_minio(
        minio_endpoint, minio_access_key, minio_secret_key, minio_bucket
    )

    # Load fixture data
    fixture_labels = _load_project_labels()
    task_fixtures = _load_task_fixtures()
    logger.info(
        f"Loaded {len(fixture_labels)} labels, {len(task_fixtures)} task fixtures"
    )

    with make_client(host=host, credentials=(username, password)) as client:
        # Register MinIO cloud storage (using internal Docker URL)
        cs_id = _register_cloud_storage(
            client, minio_bucket, minio_internal, minio_access_key, minio_secret_key
        )

        # Create project
        project = _create_project(client, fixture_labels, cs_id)

        # Get real label IDs
        real_labels = project.get_labels()
        label_id_map = _build_label_id_map(fixture_labels, real_labels)

        # Create tasks
        task_ids = {}
        for tf in task_fixtures:
            task_name = tf["task"]["name"]
            tid = _create_task(client, project.id, tf, label_id_map, cs_id)
            task_ids[task_name] = tid

    # Write seeded marker
    seeded_data = {
        "project_id": project.id,
        "project_name": "coco8-dev",
        "task_ids": task_ids,
        "cloud_storage_id": cs_id,
    }
    SEEDED_FILE.write_text(json.dumps(seeded_data, indent=2), encoding="utf-8")
    logger.info(f"Wrote seeded marker: {SEEDED_FILE}")
    logger.info("Seeding complete!")


if __name__ == "__main__":
    main()

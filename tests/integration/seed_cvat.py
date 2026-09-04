#!/usr/bin/env python3
"""Seed one run's coco8-dev project into the integration organization.

Reads the JSON fixture files from tests/fixtures/cvat/coco8-dev/ and
recreates the same project/task structure on the CVAT stand, under the run
tag: cloud storage "<tag> minio" and project "<tag> coco8-dev". Images are
uploaded from tests/fixtures/data/coco8/images/ to MinIO first.

Environment (scripts/integration_env.sh exports all of it):
  CVAT_INTEGRATION_HOST / CVAT_INTEGRATION_USER / CVAT_INTEGRATION_PASSWORD
  CVAT_INTEGRATION_ORG      organization every object is created in
  CVAT_INTEGRATION_PROJECT  full project name, "<tag> coco8-dev"
  INTEGRATION_RUN_TAG       the tag, names the cloud storage
  MINIO_ENDPOINT            MinIO as this script sees it
  MINIO_ENDPOINT_FOR_CVAT   the same MinIO as the CVAT pods see it
  MINIO_ROOT_USER / MINIO_ROOT_PASSWORD / MINIO_BUCKET

Create-only on purpose: cvat_stand.py cleanup --tag runs first, and a project
with the configured name already present is an error, not a second copy.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

if TYPE_CHECKING:
    from cvat_sdk.core.client import Client as CvatClient
    from cvat_sdk.core.proxies.projects import Project as CvatProject

import boto3
from botocore.config import Config as BotoConfig
from cvat_sdk import make_client
from cvat_sdk.api_client import models as cvat_models
from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
from cvat_sdk.core.proxies.tasks import ResourceType
from loguru import logger
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "cvat" / "coco8-dev"
IMAGES_DIR = REPO_ROOT / "tests" / "fixtures" / "data" / "coco8" / "images"

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


def _env(key: str, default: str = "") -> str:
    value = os.environ.get(key, default).strip()
    if not value:
        logger.error(f"{key} is not set; source scripts/integration_env.sh first")
        sys.exit(1)
    return value


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


class MinioAccess(BaseModel):
    """MinIO as the CVAT pods reach it, plus the bucket and its credentials."""

    endpoint_for_cvat: str
    access_key: str
    secret_key: str
    bucket: str


def _register_cloud_storage(
    client: CvatClient, display_name: str, minio: MinioAccess
) -> int:
    """Register MinIO as cloud storage in CVAT. Returns cloud_storage_id."""
    specific_attributes = urlencode(
        {
            "endpoint_url": minio.endpoint_for_cvat,
            "region_name": "us-east-1",
        }
    )
    cs_spec = cvat_models.CloudStorageWriteRequest(
        display_name=display_name,
        provider_type=cvat_models.ProviderTypeEnum("AWS_S3_BUCKET"),
        resource=minio.bucket,
        credentials_type=cvat_models.CredentialsTypeEnum("KEY_SECRET_KEY_PAIR"),
        key=minio.access_key,
        secret_key=minio.secret_key,
        specific_attributes=specific_attributes,
    )
    cs, _ = client.api_client.cloudstorages_api.create(cs_spec)
    logger.info(f"Registered cloud storage: id={cs.id}, bucket={minio.bucket}")
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


def _refuse_existing_project(client: CvatClient, name: str) -> None:
    existing = [p for p in client.projects.list() if p.name == name]
    if existing:
        ids = ", ".join(str(p.id) for p in existing)
        logger.error(
            f"project '{name}' already exists (id {ids}); "
            "run cvat_stand.py cleanup --tag first"
        )
        sys.exit(1)


def _create_project(
    client: CvatClient, name: str, labels: list[dict[str, Any]], cloud_storage_id: int
) -> CvatProject:
    """Create the run's coco8-dev project with labels and cloud storage source."""
    project_spec = {
        "name": name,
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
    host = _env("CVAT_INTEGRATION_HOST")
    username = _env("CVAT_INTEGRATION_USER")
    password = _env("CVAT_INTEGRATION_PASSWORD")
    organization = _env("CVAT_INTEGRATION_ORG")
    project_name = _env("CVAT_INTEGRATION_PROJECT")
    run_tag = _env("INTEGRATION_RUN_TAG")
    minio_endpoint = _env("MINIO_ENDPOINT")
    minio_endpoint_for_cvat = _env("MINIO_ENDPOINT_FOR_CVAT")
    minio_access_key = _env("MINIO_ROOT_USER", "minioadmin")
    minio_secret_key = _env("MINIO_ROOT_PASSWORD", "minioadmin")
    minio_bucket = _env("MINIO_BUCKET", "cveta2-test")

    logger.info(f"CVAT host: {host}, organization: {organization}")
    logger.info(
        f"MinIO endpoint: {minio_endpoint} (for CVAT: {minio_endpoint_for_cvat})"
    )

    _upload_images_to_minio(
        minio_endpoint, minio_access_key, minio_secret_key, minio_bucket
    )

    fixture_labels = _load_project_labels()
    task_fixtures = _load_task_fixtures()
    logger.info(
        f"Loaded {len(fixture_labels)} labels, {len(task_fixtures)} task fixtures"
    )

    with make_client(host=host, credentials=(username, password)) as client:
        client.organization_slug = organization
        _refuse_existing_project(client, project_name)
        cs_id = _register_cloud_storage(
            client,
            f"{run_tag} minio",
            MinioAccess(
                endpoint_for_cvat=minio_endpoint_for_cvat,
                access_key=minio_access_key,
                secret_key=minio_secret_key,
                bucket=minio_bucket,
            ),
        )
        project = _create_project(client, project_name, fixture_labels, cs_id)

        real_labels = project.get_labels()
        label_id_map = _build_label_id_map(fixture_labels, real_labels)

        for tf in task_fixtures:
            _create_task(client, project.id, tf, label_id_map, cs_id)

    logger.info(f"Seeding complete: project '{project_name}' (id={project.id})")


if __name__ == "__main__":
    main()

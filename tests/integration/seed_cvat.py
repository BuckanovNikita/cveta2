#!/usr/bin/env python3
"""Seed one run's bucket and coco8-dev project on the shared stands.

Reads the JSON fixture files from tests/fixtures/cvat/coco8-dev/ and
recreates the same project/task structure on the CVAT stand, under the run
tag: bucket "<tag>" on the shared MinIO with the coco8 images from
tests/fixtures/data/coco8/images/, cloud storage "<tag> minio" pointing at
that bucket through the in-cluster MinIO endpoint, and project
"<tag> coco8-dev" with its tasks.

Environment (scripts/integration_env.sh exports all of it):
  CVAT_INTEGRATION_HOST / CVAT_INTEGRATION_USER / CVAT_INTEGRATION_PASSWORD
  CVAT_INTEGRATION_ORG      organization every object is created in
  CVAT_INTEGRATION_PROJECT  full project name, "<tag> coco8-dev"
  INTEGRATION_RUN_TAG       the tag, names the cloud storage
  MINIO_ENDPOINT            the shared MinIO as this script sees it
  MINIO_ENDPOINT_FOR_CVAT   the same MinIO as the CVAT pods see it
  MINIO_ACCESS_KEY / MINIO_SECRET_KEY / MINIO_REGION / MINIO_BUCKET
                            the cveta2 key, its region and this run's bucket

The cveta2 key is the only credential this script knows: it owns the bucket
it creates (path-style requests, the only style the MinIO ingress accepts)
and it is what CVAT stores in the cloud storage. Create-only on purpose:
cvat_stand.py cleanup --tag and minio.py cleanup --prefix run first, so a
project with the configured name already present is an error, not a second
copy; a bucket this key already owns is reused, since a bucket is just a
container for the same images.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlencode

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from cvat_sdk.api_client import models as cvat_models
from cvat_sdk.api_client.exceptions import ApiException
from cvat_sdk.core.client import Client
from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
from cvat_sdk.core.proxies.tasks import ResourceType
from loguru import logger
from pydantic import BaseModel

if TYPE_CHECKING:
    from cvat_sdk.core.client import Client as CvatClient
    from cvat_sdk.core.proxies.projects import Project as CvatProject

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "cvat" / "coco8-dev"
IMAGES_DIR = REPO_ROOT / "tests" / "fixtures" / "data" / "coco8" / "images"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}

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

ENV_KEYS = {
    "cvat_host": "CVAT_INTEGRATION_HOST",
    "cvat_username": "CVAT_INTEGRATION_USER",
    "cvat_password": "CVAT_INTEGRATION_PASSWORD",
    "cvat_organization": "CVAT_INTEGRATION_ORG",
    "project_name": "CVAT_INTEGRATION_PROJECT",
    "run_tag": "INTEGRATION_RUN_TAG",
    "minio_endpoint": "MINIO_ENDPOINT",
    "minio_endpoint_for_cvat": "MINIO_ENDPOINT_FOR_CVAT",
    "minio_access_key": "MINIO_ACCESS_KEY",
    "minio_secret_key": "MINIO_SECRET_KEY",
    "minio_region": "MINIO_REGION",
    "minio_bucket": "MINIO_BUCKET",
}


class SeedError(RuntimeError):
    """A state the seed must not paper over."""


class SeedSettings(BaseModel):
    cvat_host: str
    cvat_username: str
    cvat_password: str
    cvat_organization: str
    project_name: str
    run_tag: str
    minio_endpoint: str
    minio_endpoint_for_cvat: str
    minio_access_key: str
    minio_secret_key: str
    minio_region: str
    minio_bucket: str

    @classmethod
    def from_env(cls) -> SeedSettings:
        values = {
            field: os.environ.get(env, "").strip() for field, env in ENV_KEYS.items()
        }
        missing = [ENV_KEYS[field] for field, value in values.items() if not value]
        if missing:
            raise SeedError(
                f"{', '.join(missing)} not set; source scripts/integration_env.sh "
                "(it exports them from the cveta2 Secrets through the k8s-infra skill)"
            )
        values["cvat_host"] = values["cvat_host"].rstrip("/")
        return cls(**values)

    @property
    def cloud_storage_name(self) -> str:
        return f"{self.run_tag} minio"


class BucketClient(Protocol):
    """The two S3 calls the seed needs from a boto3 client."""

    def create_bucket(self, *, Bucket: str) -> dict[str, Any]:  # noqa: N803
        """Create a bucket owned by the signing key."""
        ...

    def put_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Body: bytes,  # noqa: N803
    ) -> dict[str, Any]:
        """Store one object."""
        ...


def make_bucket_client(settings: SeedSettings) -> BucketClient:
    """Build a boto3 client signing as the cveta2 key, path-style, host endpoint."""
    client: BucketClient = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name=settings.minio_region,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return client


def collect_image_paths(images_dir: Path) -> list[Path]:
    """List the coco8 images, train then val, sorted; a missing directory fails."""
    paths: list[Path] = []
    for sub in ("train", "val"):
        directory = images_dir / sub
        if not directory.is_dir():
            raise SeedError(
                f"missing images directory {directory}; "
                "scripts/integration_up.sh downloads coco8 first"
            )
        paths.extend(
            p for p in sorted(directory.iterdir()) if p.suffix.lower() in IMAGE_SUFFIXES
        )
    if not paths:
        raise SeedError(f"no images under {images_dir}")
    return paths


def create_bucket(s3: BucketClient, bucket: str) -> None:
    """Create the run's bucket; one this key already owns is fine, nothing else is."""
    try:
        s3.create_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "BucketAlreadyOwnedByYou":
            raise SeedError(
                f"cannot create bucket '{bucket}': {code or exc}; the cveta2 key "
                "may create only buckets named '<its own run tag>' "
                "(minio.py --project cveta2 whoami shows the policy)"
            ) from exc
        logger.info(f"Bucket '{bucket}' already exists and is ours; reusing it")
        return
    logger.info(f"Created bucket '{bucket}'")


def upload_images(s3: BucketClient, bucket: str, paths: list[Path]) -> list[str]:
    """Upload the images flat under the bucket root; returns the object keys."""
    keys = [p.name for p in paths]
    for path in paths:
        s3.put_object(Bucket=bucket, Key=path.name, Body=path.read_bytes())
    logger.info(f"Uploaded {len(keys)} image(s) to s3://{bucket}/")
    return keys


def _register_cloud_storage(client: CvatClient, settings: SeedSettings) -> int:
    """Register the bucket as CVAT cloud storage, reached from the pods."""
    specific_attributes = urlencode(
        {
            "endpoint_url": settings.minio_endpoint_for_cvat,
            "region_name": settings.minio_region,
        }
    )
    cs_spec = cvat_models.CloudStorageWriteRequest(
        display_name=settings.cloud_storage_name,
        provider_type=cvat_models.ProviderTypeEnum("AWS_S3_BUCKET"),
        resource=settings.minio_bucket,
        credentials_type=cvat_models.CredentialsTypeEnum("KEY_SECRET_KEY_PAIR"),
        key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        specific_attributes=specific_attributes,
    )
    cs, _ = client.api_client.cloudstorages_api.create(cs_spec)
    logger.info(f"Registered cloud storage: id={cs.id}, bucket={settings.minio_bucket}")
    return int(cs.id)


def _load_project_labels() -> list[dict[str, Any]]:
    project_file = FIXTURES_DIR / "project.json"
    data = json.loads(project_file.read_text(encoding="utf-8"))
    return list(data.get("labels", []))


def _load_task_fixtures() -> list[dict[str, Any]]:
    tasks_dir = FIXTURES_DIR / "tasks"
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(tasks_dir.glob("*.json"))
    ]


def _refuse_existing_project(client: CvatClient, name: str) -> None:
    existing = [p for p in client.projects.list() if p.name == name]
    if existing:
        ids = ", ".join(str(p.id) for p in existing)
        raise SeedError(
            f"project '{name}' already exists (id {ids}); "
            "run cvat_stand.py cleanup --tag first"
        )


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


def _shapes_for(
    shapes_raw: list[dict[str, Any]], label_id_map: dict[int, int]
) -> list[Any]:
    return [
        cvat_models.LabeledShapeRequest(
            type=cvat_models.ShapeType(s["type"]),
            frame=s["frame"],
            label_id=label_id_map[s["label_id"]],
            points=s["points"],
            occluded=s.get("occluded", False),
            z_order=s.get("z_order", 0),
            rotation=s.get("rotation", 0.0),
            source=s.get("source", "manual"),
        )
        for s in shapes_raw
        if s["label_id"] in label_id_map
    ]


def _create_task(
    client: CvatClient,
    project_id: int,
    task_fixture: dict[str, Any],
    label_id_map: dict[int, int],
    cloud_storage_id: int,
) -> int:
    """Create a single task, upload annotations, delete frames. Returns task_id."""
    task_name = task_fixture["task"]["name"]
    task = client.tasks.create_from_data(
        spec={"name": task_name, "project_id": project_id, "labels": []},
        resource_type=ResourceType.SHARE,
        resources=list(IMAGE_NAMES),
        data_params={
            "cloud_storage_id": cloud_storage_id,
            "sorting_method": "natural",
        },
    )
    logger.info(f"Created task: {task_name} (id={task.id})")

    shapes = _shapes_for(
        task_fixture.get("annotations", {}).get("shapes", []), label_id_map
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
        tasks_api.partial_update_data_meta(
            task.id,
            patched_data_meta_write_request=cvat_models.PatchedDataMetaWriteRequest(
                deleted_frames=sorted(current_deleted | set(deleted_frames)),
            ),
        )
        logger.info(f"  Deleted frames {deleted_frames} in task {task.id}")

    return int(task.id)


def seed_bucket(settings: SeedSettings, s3: BucketClient, images_dir: Path) -> None:
    """Bucket <tag> with the coco8 images, uploaded from the host."""
    paths = collect_image_paths(images_dir)
    create_bucket(s3, settings.minio_bucket)
    upload_images(s3, settings.minio_bucket, paths)


def seed_project(client: CvatClient, settings: SeedSettings) -> int:
    """Cloud storage, project and tasks of this run; returns the project id."""
    fixture_labels = _load_project_labels()
    task_fixtures = _load_task_fixtures()
    logger.info(
        f"Loaded {len(fixture_labels)} labels, {len(task_fixtures)} task fixtures"
    )
    _refuse_existing_project(client, settings.project_name)
    cs_id = _register_cloud_storage(client, settings)
    project = _create_project(client, settings.project_name, fixture_labels, cs_id)
    label_id_map = _build_label_id_map(fixture_labels, project.get_labels())
    for task_fixture in task_fixtures:
        _create_task(client, project.id, task_fixture, label_id_map, cs_id)
    return int(project.id)


def open_stand(settings: SeedSettings) -> Client:
    """Log in as the cveta2 user, scoped to the organization; a refusal is fatal."""
    client = Client(settings.cvat_host, check_server_version=False)
    try:
        client.login((settings.cvat_username, settings.cvat_password))
    except ApiException as exc:
        client.close()
        raise SeedError(
            f"login as '{settings.cvat_username}' at {settings.cvat_host} failed: "
            f"{exc.status} {exc.body}; the credentials are the cveta2 Secret "
            "(`cvat.py --project cveta2 env` from the k8s-infra skill), "
            "cvat_stand.py verify tells which piece is wrong"
        ) from exc
    except OSError:
        client.close()
        raise
    client.organization_slug = settings.cvat_organization
    return client


def main() -> int:
    try:
        settings = SeedSettings.from_env()
        logger.info(
            f"CVAT host: {settings.cvat_host}, organization: "
            f"{settings.cvat_organization}"
        )
        logger.info(
            f"MinIO endpoint: {settings.minio_endpoint} "
            f"(for CVAT: {settings.minio_endpoint_for_cvat}), "
            f"bucket {settings.minio_bucket}"
        )
        seed_bucket(settings, make_bucket_client(settings), IMAGES_DIR)
        client = open_stand(settings)
        try:
            project_id = seed_project(client, settings)
        finally:
            client.close()
    except SeedError as error:
        logger.error(str(error))
        return 1
    logger.info(
        f"Seeding complete: project '{settings.project_name}' (id={project_id})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

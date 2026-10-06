"""tests/integration/seed_cvat.py against a stubbed S3 client and a fake CVAT SDK.

botocore's Stubber wraps the real boto3 client the seed builds, so every S3
call is validated against the service model and the requests carry the
cveta2 key, path-style. The fake CVAT client records what the seed creates.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from botocore.stub import ANY, Stubber
from cvat_sdk.api_client.exceptions import ApiException
from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
from cvat_sdk.core.proxies.tasks import ResourceType
from loguru import logger
from pydantic import BaseModel, ConfigDict

from tests.integration import seed_cvat

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

TAG = "cveta2-claude-20260905-integration-k3x9"
ENV = {
    "CVAT_INTEGRATION_HOST": "http://cvat.k8s.localhost/",
    "CVAT_INTEGRATION_USER": "cveta2",
    "CVAT_INTEGRATION_PASSWORD": "from-the-secret",
    "CVAT_INTEGRATION_ORG": "agents",
    "CVAT_INTEGRATION_PROJECT": f"{TAG} coco8-dev",
    "INTEGRATION_RUN_TAG": TAG,
    "MINIO_ENDPOINT": "http://minio.k8s.localhost",
    "MINIO_ENDPOINT_FOR_CVAT": "http://minio.minio.svc:9000",
    "MINIO_ACCESS_KEY": "cveta2",
    "MINIO_SECRET_KEY": "minio-secret",
    "MINIO_REGION": "us-east-1",
    "MINIO_BUCKET": TAG,
}


class Stand(BaseModel):
    """What the fake CVAT stand records."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    existing_projects: list[str] = []
    storages: list[Any] = []
    projects: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    annotations: list[tuple[int, int, Any]] = []
    deleted_frames: dict[int, list[int]] = {}
    logins: list[tuple[str, str]] = []
    password: str = "from-the-secret"
    org_slug: str | None = None
    closed: int = 0


def _fake_client_class(stand: Stand) -> type:
    def create_storage(spec: Any) -> tuple[Any, None]:
        stand.storages.append(spec)
        return SimpleNamespace(id=20 + len(stand.storages)), None

    def create_project(spec: dict[str, Any]) -> Any:
        stand.projects.append(spec)
        labels = [
            SimpleNamespace(id=1000 + i, name=label["name"])
            for i, label in enumerate(spec["labels"])
        ]
        return SimpleNamespace(
            id=len(stand.projects), name=spec["name"], get_labels=lambda: labels
        )

    def create_task(
        spec: dict[str, Any],
        resource_type: ResourceType,
        resources: list[str],
        data_params: dict[str, Any],
    ) -> Any:
        stand.tasks.append(
            {
                "spec": spec,
                "resource_type": resource_type,
                "resources": resources,
                "data_params": data_params,
            }
        )
        task_id = 100 + len(stand.tasks)

        def update_annotations(data: Any, action: Any) -> None:
            stand.annotations.append((task_id, len(data.shapes), action))

        return SimpleNamespace(id=task_id, update_annotations=update_annotations)

    def partial_update_data_meta(
        task_id: int, patched_data_meta_write_request: Any
    ) -> None:
        stand.deleted_frames[task_id] = list(
            patched_data_meta_write_request.deleted_frames
        )

    class FakeClient:
        def __init__(self, url: str, *, check_server_version: bool = True) -> None:
            assert url == "http://cvat.k8s.localhost"
            assert check_server_version is False
            self.organization_slug: str | None = None
            self.api_client = SimpleNamespace(
                cloudstorages_api=SimpleNamespace(create=create_storage),
                tasks_api=SimpleNamespace(
                    retrieve_data_meta=lambda task_id: (
                        SimpleNamespace(deleted_frames=[], task_id=task_id),
                        None,
                    ),
                    partial_update_data_meta=partial_update_data_meta,
                ),
            )
            self.projects = SimpleNamespace(
                list=lambda: [
                    SimpleNamespace(id=i, name=name)
                    for i, name in enumerate(stand.existing_projects, start=900)
                ],
                create=create_project,
            )
            self.tasks = SimpleNamespace(create_from_data=create_task)

        def login(self, credentials: tuple[str, str]) -> None:
            if credentials[1] != stand.password:
                raise ApiException(status=401, reason="Unauthorized")
            stand.logins.append(credentials)

        def close(self) -> None:
            stand.org_slug = self.organization_slug
            stand.closed += 1

    return FakeClient


@pytest.fixture
def stand(monkeypatch: pytest.MonkeyPatch) -> Stand:
    fake = Stand()
    monkeypatch.setattr(seed_cvat, "Client", _fake_client_class(fake))
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    return fake


@pytest.fixture
def images_dir(tmp_path: Path) -> Path:
    root = tmp_path / "images"
    for sub, names in (
        ("train", seed_cvat.IMAGE_NAMES[:4]),
        ("val", seed_cvat.IMAGE_NAMES[4:]),
    ):
        (root / sub).mkdir(parents=True)
        for name in names:
            (root / sub / name).write_bytes(b"jpeg-bytes-of-" + name.encode())
        (root / sub / "labels.txt").write_text("not an image", encoding="utf-8")
    return root


@pytest.fixture
def logs() -> Iterator[list[str]]:
    records: list[str] = []
    handle = logger.add(
        lambda m: records.append(str(m).rstrip("\n")), format="{message}"
    )
    yield records
    logger.remove(handle)


def _stubbed_s3(
    settings: seed_cvat.SeedSettings, keys: list[str], *, create_error: str = ""
) -> tuple[Any, Stubber]:
    s3: Any = seed_cvat.make_bucket_client(settings)
    stubber = Stubber(s3)
    if create_error:
        stubber.add_client_error(
            "create_bucket",
            create_error,
            expected_params={"Bucket": settings.minio_bucket},
        )
    else:
        stubber.add_response("create_bucket", {}, {"Bucket": settings.minio_bucket})
    if create_error in ("", "BucketAlreadyOwnedByYou"):
        for key in keys:
            stubber.add_response(
                "put_object",
                {},
                {"Bucket": settings.minio_bucket, "Key": key, "Body": ANY},
            )
    return s3, stubber


class TestSettings:
    @pytest.mark.usefixtures("stand")
    def test_every_missing_variable_is_named_at_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MINIO_REGION")
        monkeypatch.setenv("MINIO_BUCKET", "  ")
        with pytest.raises(seed_cvat.SeedError) as error:
            seed_cvat.SeedSettings.from_env()
        assert "MINIO_REGION, MINIO_BUCKET not set" in str(error.value)
        assert "integration_env.sh" in str(error.value)

    @pytest.mark.usefixtures("stand")
    def test_names_derive_from_the_tag_and_the_host_loses_its_slash(self) -> None:
        settings = seed_cvat.SeedSettings.from_env()
        assert settings.cvat_host == "http://cvat.k8s.localhost"
        assert settings.cloud_storage_name == f"{TAG} minio"
        assert settings.minio_bucket == TAG


class TestBucket:
    @pytest.mark.usefixtures("stand")
    def test_the_client_signs_as_the_cveta2_key_path_style(self) -> None:
        s3: Any = seed_cvat.make_bucket_client(seed_cvat.SeedSettings.from_env())
        assert s3.meta.endpoint_url == "http://minio.k8s.localhost"
        assert s3.meta.config.s3 == {"addressing_style": "path"}
        assert s3.meta.config.signature_version == "s3v4"
        assert s3.meta.region_name == "us-east-1"
        credentials = s3._request_signer._credentials
        assert (credentials.access_key, credentials.secret_key) == (
            "cveta2",
            "minio-secret",
        )

    @pytest.mark.usefixtures("stand")
    def test_creates_the_bucket_and_uploads_the_images_flat(
        self, images_dir: Path, logs: list[str]
    ) -> None:
        settings = seed_cvat.SeedSettings.from_env()
        s3, stubber = _stubbed_s3(settings, seed_cvat.IMAGE_NAMES)
        with stubber:
            seed_cvat.seed_bucket(settings, s3, images_dir)
        stubber.assert_no_pending_responses()
        assert f"Created bucket '{TAG}'" in logs
        assert f"Uploaded 8 image(s) to s3://{TAG}/" in logs

    @pytest.mark.usefixtures("stand")
    def test_a_bucket_this_key_owns_is_reused(
        self, images_dir: Path, logs: list[str]
    ) -> None:
        settings = seed_cvat.SeedSettings.from_env()
        s3, stubber = _stubbed_s3(
            settings, seed_cvat.IMAGE_NAMES, create_error="BucketAlreadyOwnedByYou"
        )
        with stubber:
            seed_cvat.seed_bucket(settings, s3, images_dir)
        stubber.assert_no_pending_responses()
        assert any("already exists and is ours" in line for line in logs)

    @pytest.mark.usefixtures("stand")
    @pytest.mark.parametrize("code", ["BucketAlreadyExists", "AccessDenied"])
    def test_somebody_elses_bucket_or_a_denied_key_is_an_error(
        self, images_dir: Path, code: str
    ) -> None:
        settings = seed_cvat.SeedSettings.from_env()
        s3, stubber = _stubbed_s3(settings, [], create_error=code)
        with stubber, pytest.raises(seed_cvat.SeedError) as error:
            seed_cvat.seed_bucket(settings, s3, images_dir)
        assert f"cannot create bucket '{TAG}': {code}" in str(error.value)

    @pytest.mark.usefixtures("stand")
    def test_missing_images_are_reported_before_anything_is_created(
        self, tmp_path: Path
    ) -> None:
        settings = seed_cvat.SeedSettings.from_env()
        s3, stubber = _stubbed_s3(settings, [])
        with stubber, pytest.raises(seed_cvat.SeedError) as error:
            seed_cvat.seed_bucket(settings, s3, tmp_path / "nowhere")
        assert "missing images directory" in str(error.value)
        assert "integration_up.sh" in str(error.value)
        with pytest.raises(AssertionError, match="1 responses remaining"):
            stubber.assert_no_pending_responses()


class TestProject:
    def test_storage_project_and_tasks_follow_the_fixtures(self, stand: Stand) -> None:
        settings = seed_cvat.SeedSettings.from_env()
        client = seed_cvat.open_stand(settings)
        try:
            project_id = seed_cvat.seed_project(client, settings)
        finally:
            client.close()

        assert stand.logins == [("cveta2", "from-the-secret")]
        assert stand.org_slug == "agents"
        assert stand.closed == 1

        (storage,) = stand.storages
        assert storage.display_name == f"{TAG} minio"
        assert storage.resource == TAG
        assert (storage.key, storage.secret_key) == ("cveta2", "minio-secret")
        assert "endpoint_url=http%3A%2F%2Fminio.minio.svc%3A9000" in (
            storage.specific_attributes
        )
        assert "region_name=us-east-1" in storage.specific_attributes

        (project,) = stand.projects
        assert project_id == 1
        assert project["name"] == f"{TAG} coco8-dev"
        assert project["source_storage"] == {
            "location": "cloud_storage",
            "cloud_storage_id": 21,
        }
        assert project["target_storage"]["cloud_storage_id"] == 21
        assert {"name": "person"} in project["labels"]

        assert [t["spec"]["name"] for t in stand.tasks] == [
            "normal",
            "all-empty",
            "all-removed",
            "zero-frame-empty-last-removed",
            "all-bboxes-moved",
            "all-except-first-empty",
            "frames-1-2-removed",
        ]
        for task in stand.tasks:
            assert task["spec"]["project_id"] == 1
            assert task["resource_type"] is ResourceType.SHARE
            assert task["resources"] == seed_cvat.IMAGE_NAMES
            assert task["data_params"]["cloud_storage_id"] == 21
        annotated = {task_id for task_id, _, _ in stand.annotations}
        assert 102 not in annotated, "all-empty carries no shapes"
        assert all(count > 0 for _, count, _ in stand.annotations)
        assert {action for _, _, action in stand.annotations} == {
            AnnotationUpdateAction.CREATE
        }
        assert stand.deleted_frames == {
            103: [0, 1, 2, 3, 4, 5, 6, 7],
            104: [7],
            107: [1, 2],
        }

    def test_an_existing_project_of_this_name_is_refused(self, stand: Stand) -> None:
        stand.existing_projects = [f"{TAG} coco8-dev"]
        settings = seed_cvat.SeedSettings.from_env()
        client = seed_cvat.open_stand(settings)
        with pytest.raises(seed_cvat.SeedError) as error:
            seed_cvat.seed_project(client, settings)
        assert "already exists (id 900)" in str(error.value)
        assert "cvat_stand.py cleanup --tag" in str(error.value)
        assert stand.storages == []
        assert stand.projects == []

    def test_the_source_embeds_no_root_credential(self) -> None:
        source = seed_cvat.__file__
        with open(source, encoding="utf-8") as handle:  # noqa: PTH123
            text = handle.read()
        assert "minioadmin" not in text
        assert "localhost:9" not in text


class TestMain:
    def test_a_rejected_login_is_one_log_line_and_exit_1(
        self,
        stand: Stand,
        monkeypatch: pytest.MonkeyPatch,
        logs: list[str],
        images_dir: Path,
    ) -> None:
        stand.password = "rotated"
        monkeypatch.setattr(seed_cvat, "IMAGES_DIR", images_dir)
        settings = seed_cvat.SeedSettings.from_env()
        s3, stubber = _stubbed_s3(settings, seed_cvat.IMAGE_NAMES)
        monkeypatch.setattr(seed_cvat, "make_bucket_client", lambda _settings: s3)
        monkeypatch.setattr(sys, "argv", ["seed_cvat.py"])
        with stubber:
            assert seed_cvat.main() == 1
        assert logs[-1].startswith(
            "login as 'cveta2' at http://cvat.k8s.localhost failed: 401"
        )
        assert "cvat_stand.py verify" in logs[-1]
        assert stand.closed == 1
        assert stand.projects == []

    def test_a_settings_error_is_one_log_line_and_exit_1(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        monkeypatch.delenv("MINIO_SECRET_KEY")
        monkeypatch.setattr(sys, "argv", ["seed_cvat.py"])
        assert seed_cvat.main() == 1
        assert logs[-1].startswith("MINIO_SECRET_KEY not set")
        assert stand.logins == []

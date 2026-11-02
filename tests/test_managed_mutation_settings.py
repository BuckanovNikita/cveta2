"""Behavioral ownership boundaries for config load and save mutation coverage."""

from pathlib import Path

import pytest
import yaml

from cveta2.adapters.config.project import load_project_config
from cveta2.adapters.config.settings import (
    CacheConfig,
    CacheProjectSettings,
    CvatConfig,
    IgnoreConfig,
    SyncRootsConfig,
)
from cveta2.domain.managed.models import ManagedError, MigrationRequired
from tests.helpers import write_config_yaml, write_split_config_yaml


def shared_personal(path: Path) -> Path:
    """Create an explicit shared identity with independently owned credentials."""
    return write_split_config_yaml(
        path,
        project_ids={"Source": 71},
        cvat={
            "host": "https://shared.example",
            "organization": "team",
            "username": "old-user",
            "password": "old-password",
        },
        image_cache={"Source": "/local/images"},
    )


@pytest.mark.parametrize("organization", ["team", "other-team"])
def test_shared_loader_accepts_only_matching_environment_organization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, organization: str
) -> None:
    """Organization identity is checked independently from the matching host."""
    path = shared_personal(tmp_path / "personal.yaml")
    monkeypatch.setenv("CVAT_HOST", "https://shared.example/")
    monkeypatch.setenv("CVAT_ORGANIZATION", organization)
    monkeypatch.setenv("CVAT_USERNAME", "env-user")
    monkeypatch.setenv("CVAT_PASSWORD", "env-password")
    monkeypatch.setenv("CVETA2_DATA_TIMEOUT", "7.5")
    if organization != "team":
        with pytest.raises(ManagedError) as error:
            CvatConfig.load(path)
        assert isinstance(error.value.args[0], str)
        assert str(error.value)
    else:
        config = CvatConfig.load(path)
        assert config.host == "https://shared.example"
        assert config.organization == "team"
        assert config.username == "env-user"
        assert config.password == "env-password"
        assert config.request_timeout == 7.5


@pytest.mark.parametrize(
    ("host", "organization"),
    [("https://different.example", "team"), ("https://shared.example", "other")],
)
def test_shared_credentials_save_refuses_either_identity_change(
    tmp_path: Path, host: str, organization: str
) -> None:
    """A host-only or organization-only mismatch must refuse before writing."""
    path = shared_personal(tmp_path / "personal.yaml")
    original = path.read_bytes()
    with pytest.raises(ManagedError) as error:
        CvatConfig(host=host, organization=organization, username="new").save_to_file(
            path
        )
    assert isinstance(error.value.args[0], str)
    assert str(error.value)
    assert path.read_bytes() == original
    assert load_project_config(path).cvat.host == "https://shared.example"


def test_shared_credentials_save_omits_identity_and_preserves_local_settings(
    tmp_path: Path,
) -> None:
    """Saving credentials cannot copy either shared identity field personally."""
    path = shared_personal(tmp_path / "personal.yaml")
    config = CvatConfig(
        host="https://shared.example",
        organization="team",
        username="new-user",
        password="new-password",
        request_timeout=15,
    )
    config.save_to_file(path)
    saved = yaml.safe_load(path.read_bytes())
    assert saved["cvat"] == {
        "username": "new-user",
        "password": "new-password",
        "request_timeout": 15,
    }
    assert saved["image_cache"] == {"Source": "/local/images"}
    assert saved["schema_version"] == 1
    assert CvatConfig.load(path).host == "https://shared.example"
    assert CvatConfig.load(path).organization == "team"


@pytest.mark.parametrize("section", ["sync", "ignore"])
def test_new_policy_save_requires_attached_shared_file(
    tmp_path: Path, section: str
) -> None:
    """Policy writers cannot manufacture a fresh personal policy section."""
    path = tmp_path / "personal.yaml"
    config: SyncRootsConfig | IgnoreConfig
    if section == "sync":
        config = SyncRootsConfig(projects={"Source": "s3://bucket/images"})
    else:
        config = IgnoreConfig()
        config.add_task("Source", 73, "ignored")
    with pytest.raises(MigrationRequired) as error:
        config.save(path)
    assert isinstance(error.value.args[0], str)
    assert str(error.value)
    assert {"setup", "--project-config"}.issubset(str(error.value).split())
    assert not path.exists()


@pytest.mark.parametrize("policy", ["ignored_prefix", "task_cache_s3"])
def test_new_cache_policy_save_requires_attached_shared_file(
    tmp_path: Path, policy: str
) -> None:
    """Each independent shared cache field requires authoritative storage."""
    path = tmp_path / "personal.yaml"
    settings = CacheProjectSettings.model_validate({policy: "s3://bucket/images"})
    with pytest.raises(MigrationRequired) as error:
        CacheConfig(projects={"Source": settings}).save(path)
    assert isinstance(error.value.args[0], str)
    assert str(error.value)
    assert not path.exists()


def test_unattached_local_cache_save_preserves_only_supported_nonempty_fields(
    tmp_path: Path,
) -> None:
    """Local cache records are legal without shared policy and have one schema."""
    path = write_config_yaml(tmp_path / "personal.yaml")
    cache = CacheConfig(
        images_root=Path("/local/root"),
        projects={
            "kept": CacheProjectSettings(images_root=Path("/local/kept")),
            "empty": CacheProjectSettings(),
        },
    )
    cache.save(path)
    saved = yaml.safe_load(path.read_bytes())
    assert saved["cache"] == {
        "images_root": "/local/root",
        "projects": {"kept": {"images_root": "/local/kept"}},
    }
    assert CacheConfig.load(path).projects == {
        "kept": CacheProjectSettings(images_root=Path("/local/kept"))
    }


def test_empty_local_cache_save_does_not_invent_policy_or_raise(tmp_path: Path) -> None:
    """Empty serialized local settings must not enter cache-policy inspection."""
    path = tmp_path / "personal.yaml"
    CacheConfig().save(path)
    assert yaml.safe_load(path.read_bytes()) == {}
    assert CacheConfig.load(path) == CacheConfig()

"""Shared and personal CVAT workspace aliases must describe one identity."""

from pathlib import Path

import pytest
import yaml

from cveta2.adapters.config.project import load_project_config
from cveta2.adapters.config.settings import CvatConfig
from cveta2.domain.managed.models import CvatIdentity, ManagedError


def test_blank_shared_organization_allows_credential_save(tmp_path: Path) -> None:
    """Loading then saving credentials cannot reject an unchanged workspace."""
    shared = tmp_path / "shared.yaml"
    shared.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "cvat": {"host": "https://cvat.example", "organization": ""},
            }
        )
    )
    personal = tmp_path / "personal.yaml"
    personal.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "project_config": str(shared),
                "cvat": {"username": "alice", "password": "old"},
            }
        )
    )
    original_shared = shared.read_bytes()
    config = CvatConfig.load(personal)
    assert config.organization is None
    assert load_project_config(personal).cvat.organization is None
    config.model_copy(update={"password": "new"}).save_to_file(personal)
    assert CvatConfig.load(personal).password == "new"
    assert shared.read_bytes() == original_shared
    assert "organization" not in yaml.safe_load(personal.read_bytes())["cvat"]


def test_blank_organization_is_the_same_neutral_workspace() -> None:
    """Canonical identity and hashes must not depend on null versus empty YAML."""
    assert CvatIdentity(host="https://cvat.example", organization="") == CvatIdentity(
        host="https://cvat.example"
    )
    assert CvatConfig(organization="").organization is None


def test_empty_environment_organization_does_not_override_shared_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty environment value is unset, while a conflicting name is refused."""
    shared = tmp_path / "shared.yaml"
    shared.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "cvat": {"host": "https://cvat.example", "organization": "team"},
            }
        )
    )
    personal = tmp_path / "personal.yaml"
    personal.write_text(
        yaml.safe_dump({"schema_version": 1, "project_config": str(shared)})
    )
    monkeypatch.setenv("CVAT_ORGANIZATION", "")
    assert CvatConfig.load(personal).organization == "team"
    monkeypatch.setenv("CVAT_ORGANIZATION", "other")
    with pytest.raises(ManagedError, match="conflict"):
        CvatConfig.load(personal)

"""Final-review regressions prevent lost policy and unreadable attachments."""

from pathlib import Path

import pytest
import yaml

from cveta2.adapters.config.project import (
    activate_migration,
    attach_project_config,
    migration_proposal,
)
from cveta2.domain.managed.models import ManagedError, MigrationRequired


def _legacy(
    tmp_path: Path, names: dict[str, int], ignore: dict[str, object] | None = None
) -> Path:
    path = tmp_path / "personal.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "cvat": {"host": "https://cvat.example"},
                "sync_roots": {
                    name: f"s3://bucket/{identity}" for name, identity in names.items()
                },
                "ignore": ignore or {},
            }
        )
    )
    (tmp_path / "projects.yaml").write_text(
        yaml.safe_dump(
            {
                "organizations": [
                    {
                        "slug": "",
                        "projects": [
                            {"id": identity, "name": name}
                            for name, identity in names.items()
                        ],
                    }
                ]
            }
        )
    )
    return path


def test_migration_key_collision_requires_review_without_losing_active_policy(
    tmp_path: Path,
) -> None:
    """Generated and literal project keys cannot silently overwrite each other."""
    path = _legacy(tmp_path, {"A B": 7, "project-7": 8})
    original = path.read_bytes()
    proposal = migration_proposal(path)
    assert any("collision" in reason.lower() for reason in proposal.unresolved)
    with pytest.raises(ManagedError, match="unresolved"):
        activate_migration(proposal)
    assert path.read_bytes() == original
    assert not proposal.shared_path.exists()


@pytest.mark.parametrize("legacy_key", ["sync_roots", "ignore", "unknown_section"])
def test_attachment_validates_final_versioned_bytes_before_write(
    tmp_path: Path, legacy_key: str
) -> None:
    """Empty obsolete sections must not become invalid version-one state."""
    personal = tmp_path / "personal.yaml"
    personal.write_text(yaml.safe_dump({"cvat": {"username": "alice"}, legacy_key: {}}))
    shared = tmp_path / "shared.yaml"
    shared.write_text(
        yaml.safe_dump({"schema_version": 1, "cvat": {"host": "https://cvat.example"}})
    )
    original = personal.read_bytes()
    with pytest.raises(MigrationRequired):
        attach_project_config(personal, shared)
    assert personal.read_bytes() == original


def test_numeric_string_ignore_entries_survive_reviewed_migration(
    tmp_path: Path,
) -> None:
    """Legacy scalar and dictionary IDs retain the same exclusion semantics."""
    path = _legacy(
        tmp_path,
        {"main": 7},
        {"main": [" 42 ", {"id": "43", "name": "old", "silent": True}]},
    )
    proposal = migration_proposal(path)
    assert not proposal.unresolved
    activate_migration(proposal)
    shared = yaml.safe_load(proposal.shared_path.read_bytes())
    assert shared["projects"]["main"]["ignore"] == [
        {"id": 42, "name": ""},
        {"id": 43, "name": "old", "description": "", "silent": True},
    ]

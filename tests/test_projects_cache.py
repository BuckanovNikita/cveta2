"""Tests for cveta2/projects_cache.py — org-keyed YAML project cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cveta2.models import ProjectInfo
from cveta2.projects_cache import (
    OrgProjects,
    load_orgs_cache,
    load_projects_cache,
    save_orgs_cache,
    update_org_projects,
)

if TYPE_CHECKING:
    from pathlib import Path


def _org(slug: str, *projects: ProjectInfo) -> OrgProjects:
    return OrgProjects(
        slug=slug, name=slug or "Личное пространство", projects=list(projects)
    )


def test_missing_file_returns_empty_list(tmp_path: Path) -> None:
    assert load_orgs_cache(tmp_path / "nonexistent.yaml") == []
    assert load_projects_cache(tmp_path / "nonexistent.yaml") == []


def test_invalid_yaml_returns_empty_list(
    tmp_path: Path, capture_logs: list[str]
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(": : :", encoding="utf-8")
    assert load_orgs_cache(bad) == []
    assert any("Failed to load" in m for m in capture_logs)


def test_non_dict_top_level_returns_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")
    assert load_orgs_cache(path) == []


def test_legacy_flat_format_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "legacy.yaml"
    path.write_text(
        "projects:\n  - id: 1\n    name: alpha\n",
        encoding="utf-8",
    )
    assert load_orgs_cache(path) == []
    assert load_projects_cache(path) == []


def test_skips_invalid_org_entry_with_warning(
    tmp_path: Path, capture_logs: list[str]
) -> None:
    path = tmp_path / "bad_entry.yaml"
    path.write_text(
        "organizations:\n"
        "  - slug: ok\n"
        "    name: OK\n"
        "    projects:\n"
        "      - id: 1\n"
        "        name: alpha\n"
        "  - slug: broken\n",
        encoding="utf-8",
    )
    result = load_orgs_cache(path)
    assert [org.slug for org in result] == ["ok"]
    assert any("Skipping invalid" in m for m in capture_logs)


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "cache.yaml"
    save_orgs_cache([_org("", ProjectInfo(id=1, name="x"))], nested)
    assert nested.is_file()


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "roundtrip.yaml"
    orgs = [
        _org("", ProjectInfo(id=10, name="proj-a")),
        _org("acme", ProjectInfo(id=20, name="proj-b"), ProjectInfo(id=21, name="c")),
    ]
    save_orgs_cache(orgs, path)
    assert load_orgs_cache(path) == orgs


def test_save_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    save_orgs_cache([], path)
    assert load_orgs_cache(path) == []


def test_load_projects_cache_merges_all_orgs(tmp_path: Path) -> None:
    path = tmp_path / "cache.yaml"
    save_orgs_cache(
        [
            _org("", ProjectInfo(id=1, name="personal")),
            _org("acme", ProjectInfo(id=2, name="acme-proj")),
        ],
        path,
    )
    assert {p.name for p in load_projects_cache(path)} == {"personal", "acme-proj"}


def test_load_projects_cache_filters_by_org(tmp_path: Path) -> None:
    path = tmp_path / "cache.yaml"
    save_orgs_cache(
        [
            _org("", ProjectInfo(id=1, name="personal")),
            _org("acme", ProjectInfo(id=2, name="acme-proj")),
        ],
        path,
    )
    assert [p.name for p in load_projects_cache(path, org="acme")] == ["acme-proj"]
    assert [p.name for p in load_projects_cache(path, org="")] == ["personal"]
    assert load_projects_cache(path, org="ghost") == []


def test_update_org_projects_replaces_only_that_org(tmp_path: Path) -> None:
    path = tmp_path / "cache.yaml"
    save_orgs_cache(
        [
            _org("", ProjectInfo(id=1, name="personal")),
            _org("acme", ProjectInfo(id=2, name="old")),
        ],
        path,
    )
    update_org_projects("acme", "Acme", [ProjectInfo(id=3, name="new")], path)
    loaded = {org.slug: org for org in load_orgs_cache(path)}
    assert [p.name for p in loaded[""].projects] == ["personal"]
    assert [p.name for p in loaded["acme"].projects] == ["new"]
    assert loaded["acme"].name == "Acme"

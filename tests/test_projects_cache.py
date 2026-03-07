"""Tests for cveta2/projects_cache.py — load/save YAML project cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cveta2.models import ProjectInfo
from cveta2.projects_cache import load_projects_cache, save_projects_cache

if TYPE_CHECKING:
    from pathlib import Path


def test_missing_file_returns_empty_list(tmp_path: Path) -> None:
    assert load_projects_cache(tmp_path / "nonexistent.yaml") == []


def test_invalid_yaml_returns_empty_list(
    tmp_path: Path, capture_logs: list[str]
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(": : :", encoding="utf-8")
    assert load_projects_cache(bad) == []
    assert any("Failed to load" in m for m in capture_logs)


def test_non_dict_top_level_returns_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")
    assert load_projects_cache(path) == []


def test_missing_projects_key_returns_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "no_key.yaml"
    path.write_text("other_key: 123\n", encoding="utf-8")
    assert load_projects_cache(path) == []


def test_skips_entries_without_id_or_name(tmp_path: Path) -> None:
    path = tmp_path / "partial.yaml"
    path.write_text(
        "projects:\n  - id: 1\n  - name: foo\n  - other: bar\n",
        encoding="utf-8",
    )
    assert load_projects_cache(path) == []


def test_skips_invalid_id_with_warning(tmp_path: Path, capture_logs: list[str]) -> None:
    path = tmp_path / "bad_id.yaml"
    path.write_text(
        "projects:\n  - id: not_a_number\n    name: test\n",
        encoding="utf-8",
    )
    assert load_projects_cache(path) == []
    assert any("Skipping invalid" in m for m in capture_logs)


def test_multiple_valid_entries(tmp_path: Path) -> None:
    path = tmp_path / "ok.yaml"
    path.write_text(
        "projects:\n"
        "  - id: 1\n    name: alpha\n"
        "  - id: 2\n    name: beta\n"
        "  - id: 3\n    name: gamma\n",
        encoding="utf-8",
    )
    result = load_projects_cache(path)
    assert result == [
        ProjectInfo(id=1, name="alpha"),
        ProjectInfo(id=2, name="beta"),
        ProjectInfo(id=3, name="gamma"),
    ]


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "cache.yaml"
    save_projects_cache([ProjectInfo(id=1, name="x")], nested)
    assert nested.is_file()


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "roundtrip.yaml"
    projects = [
        ProjectInfo(id=10, name="proj-a"),
        ProjectInfo(id=20, name="proj-b"),
    ]
    save_projects_cache(projects, path)
    loaded = load_projects_cache(path)
    assert loaded == projects


def test_save_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    save_projects_cache([], path)
    assert load_projects_cache(path) == []


@pytest.mark.parametrize(
    ("id_val", "name_val"),
    [("42", "str-id"), (42.0, "float-id")],
    ids=["string-id", "float-id"],
)
def test_coerces_numeric_id(tmp_path: Path, id_val: object, name_val: str) -> None:
    path = tmp_path / "coerce.yaml"
    path.write_text(
        f"projects:\n  - id: {id_val}\n    name: {name_val}\n",
        encoding="utf-8",
    )
    result = load_projects_cache(path)
    assert len(result) == 1
    assert result[0].id == 42
    assert result[0].name == name_val

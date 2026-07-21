"""Tests for group-shared filesystem helpers."""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cveta2.fs_utils import ensure_shared_dir, write_shared_bytes

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def restrictive_umask() -> Iterator[None]:
    old = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(old)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.usefixtures("restrictive_umask")
def test_ensure_shared_dir_sets_775_on_all_new_levels(tmp_path: Path) -> None:
    leaf = tmp_path / "a" / "b" / "c"
    ensure_shared_dir(leaf)
    assert _mode(tmp_path / "a") == 0o775
    assert _mode(tmp_path / "a" / "b") == 0o775
    assert _mode(leaf) == 0o775


@pytest.mark.usefixtures("restrictive_umask")
def test_ensure_shared_dir_leaves_existing_dir_mode(tmp_path: Path) -> None:
    existing = tmp_path / "keep"
    existing.mkdir(mode=0o700)
    ensure_shared_dir(existing)
    assert _mode(existing) == 0o700


@pytest.mark.usefixtures("restrictive_umask")
def test_write_shared_bytes_sets_664(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    write_shared_bytes(target, b"payload")
    assert target.read_bytes() == b"payload"
    assert _mode(target) == 0o664


def test_chmod_failure_is_swallowed(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    with patch("pathlib.Path.chmod", side_effect=PermissionError("denied")):
        write_shared_bytes(target, b"payload")
        ensure_shared_dir(tmp_path / "new")
    assert target.read_bytes() == b"payload"
    assert (tmp_path / "new").is_dir()

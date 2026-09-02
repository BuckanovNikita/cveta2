"""Tests for group-shared filesystem helpers."""

from __future__ import annotations

import errno
import os
import stat
import threading
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cveta2.fs_utils import ensure_shared_dir, replace_shared_bytes, write_shared_bytes

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


def _temp_leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if ".tmp" in p.name)


@pytest.mark.usefixtures("restrictive_umask")
def test_replace_shared_bytes_lands_the_file_in_a_fresh_shared_dir(
    tmp_path: Path,
) -> None:
    target = tmp_path / "new" / "deeper" / "entry.json"

    replace_shared_bytes(target, b"payload")

    assert target.read_bytes() == b"payload"
    assert _mode(target) == 0o664
    assert _mode(target.parent) == 0o775
    assert _temp_leftovers(target.parent) == []


def test_replace_shared_bytes_overwrites_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "entry.json"
    target.write_bytes(b"old")

    replace_shared_bytes(target, b"new")

    assert target.read_bytes() == b"new"
    assert _temp_leftovers(tmp_path) == []


def test_replace_shared_bytes_writes_through_a_name_unique_to_the_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[Path] = []

    def record_then_write(path: Path, data: bytes) -> None:
        written.append(path)
        write_shared_bytes(path, data)

    monkeypatch.setattr("cveta2.fs_utils.write_shared_bytes", record_then_write)
    target = tmp_path / "entry.json"

    replace_shared_bytes(target, b"payload")

    expected_name = f"entry.json.tmp{os.getpid()}-{threading.get_ident()}"
    assert written == [target.with_name(expected_name)]


def test_replace_shared_bytes_removes_the_partial_temp_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write_a_prefix_then_fail(path: Path, data: bytes) -> None:
        path.write_bytes(data[:3])
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("cveta2.fs_utils.write_shared_bytes", write_a_prefix_then_fail)
    target = tmp_path / "entry.json"

    with pytest.raises(OSError, match="No space left"):
        replace_shared_bytes(target, b"payload")

    assert not target.exists()
    assert _temp_leftovers(tmp_path) == []


def test_replace_shared_bytes_reraises_when_no_temp_file_was_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_to_write(_path: Path, _data: bytes) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("cveta2.fs_utils.write_shared_bytes", refuse_to_write)
    target = tmp_path / "entry.json"

    with pytest.raises(OSError, match="No space left"):
        replace_shared_bytes(target, b"payload")

    assert not target.exists()
    assert _temp_leftovers(tmp_path) == []

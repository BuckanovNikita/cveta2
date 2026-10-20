"""Bundle policy regression contracts."""

import os
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path

import pandas as pd
import pytest

from cveta2.adapters.files.bundle_paths import LocalRoots
from cveta2.domain.bundle.models import ImageRoots, UploadError


def test_roots_resolve_symlinks_and_use_path_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "images"
    root.mkdir()
    outside = tmp_path / "images-other"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    paths = [
        str(root / "ok.png"),
        str(root / "escape" / "bad.png"),
        str(outside / "bad.png"),
    ]
    roots = LocalRoots()
    assert roots.check_local_root(str(root)) == str(root.resolve())
    assert roots.uncovered_paths(
        pd.DataFrame({"image_path": paths}), ImageRoots(local_root=[str(root)])
    ) == [str(outside / "bad.png")]


@pytest.mark.parametrize(
    "value", ["relative.png", "", None, "s3://bucket/a.png", "bad\x00path"]
)
def test_malformed_or_relative_image_paths_block(value: object) -> None:
    with pytest.raises(UploadError):
        LocalRoots().uncovered_paths(
            pd.DataFrame({"image_path": [value]}), ImageRoots()
        )


def test_every_root_is_checked(tmp_path: Path) -> None:
    with pytest.raises(UploadError):
        LocalRoots().uncovered_paths(
            pd.DataFrame({"image_path": [str(tmp_path / "image.png")]}),
            ImageRoots(local_root=[str(tmp_path), str(tmp_path / "missing")]),
        )


def test_s3_roots_are_independent_and_boundary_checked() -> None:
    checks = LocalRoots()
    roots = ImageRoots(s3_root=["s3://bucket/prefix"])
    checks.check_s3_paths(
        pd.DataFrame({"s3_image_path": ["", None, "s3://bucket/prefix/a.png"]}), roots
    )
    for value in [
        "s3://bucket/prefix-other/a.png",
        "s3://other/prefix/a.png",
        "https://bucket/prefix/a",
    ]:
        with pytest.raises(UploadError):
            checks.check_s3_paths(pd.DataFrame({"s3_image_path": [value]}), roots)


@pytest.mark.parametrize(
    "root",
    [
        "https://bucket/a",
        "s3:///a",
        "s3://bucket/a/../b",
        "s3://bucket//prefix",
        "s3://bucket/prefix//",
    ],
)
def test_invalid_s3_root_blocks_even_without_references(root: str) -> None:
    with pytest.raises(UploadError):
        LocalRoots().check_s3_paths(pd.DataFrame(), ImageRoots(s3_root=[root]))


def test_bucket_relative_keys_resolve_only_to_one_approved_bucket() -> None:
    checks = LocalRoots()
    frame = pd.DataFrame({"s3_image_path": ["prefix/a.png"]})
    checks.check_s3_paths(frame, ImageRoots(s3_root=["s3://bucket/prefix"]))
    checks.check_s3_paths(
        frame, ImageRoots(s3_root=["s3://bucket/prefix", "s3://bucket/prefix/a.png"])
    )
    with pytest.raises(UploadError, match="outside approved"):
        checks.check_s3_paths(
            frame,
            ImageRoots(s3_root=["s3://bucket/prefix", "s3://other/prefix"]),
        )
    with pytest.raises(UploadError, match="outside approved"):
        checks.check_s3_paths(frame, ImageRoots(s3_root=["s3://bucket/different"]))


@pytest.mark.parametrize(
    "value",
    [
        "prefix/../a.png",
        "prefix//a.png",
        "prefix/a.png?secret=1",
        "/prefix/a.png",
        "prefix/a.png/",
        "s3://bucket//prefix/a.png",
        "s3://bucket/prefix/a.png/",
        "s3://bucket/",
    ],
)
def test_bucket_relative_keys_reject_traversal_and_ambiguous_segments(
    value: str,
) -> None:
    with pytest.raises(UploadError):
        LocalRoots().check_s3_paths(
            pd.DataFrame({"s3_image_path": [value]}),
            ImageRoots(s3_root=["s3://bucket"]),
        )


@pytest.mark.parametrize("root", ["s3://bucket/", "s3://bucket/prefix/"])
def test_one_trailing_root_separator_preserves_key_boundaries(root: str) -> None:
    LocalRoots().check_s3_paths(
        pd.DataFrame({"s3_image_path": ["prefix/a.png", "s3://bucket/prefix/b.png"]}),
        ImageRoots(s3_root=[root]),
    )


def test_unreadable_unused_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "unused"
    root.mkdir()
    original = os.scandir

    def inaccessible(path: Path) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        if path == root:
            raise PermissionError("root cannot be read")
        return original(path)

    monkeypatch.setattr(os, "scandir", inaccessible)
    with pytest.raises(UploadError, match=r"cannot|Cannot|access"):
        LocalRoots().check_local_root(str(root))

"""Tests for image_uploader module — server file mapping and image lookup."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from cveta2.image_uploader import build_server_file_mapping, resolve_images
from cveta2.s3_utils import build_s3_key
from tests.helpers import make_cs_info

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.image_downloader import CloudStorageInfo

_MONTH_PREFIX_RE = re.compile(r"\d{4}-\d{2}/.+")


def _make_cs_info() -> CloudStorageInfo:
    return make_cs_info(prefix="project/images")


def _mock_s3_client(objects: list[tuple[str, str]]) -> MagicMock:
    """Create a mock S3 client that returns *objects* from list_objects_v2.

    *objects* is a list of ``(key, name)`` pairs where *name* is the
    relative path under the prefix.
    """
    s3 = MagicMock()
    s3.list_objects_v2.return_value = {
        "Contents": [{"Key": key} for key, _ in objects],
        "IsTruncated": False,
    }
    return s3


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


class TestResolveImages:
    """Tests for resolve_images() — direct and recursive lookup."""

    def test_flat_direct_match(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "a.jpg")
        found, missing = resolve_images(["a.jpg"], [tmp_path])
        assert found == {"a.jpg": img}
        assert missing == []

    def test_subpath_name_direct_match(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "sub" / "a.jpg")
        found, missing = resolve_images(["sub/a.jpg"], [tmp_path])
        assert found == {"sub/a.jpg": img}
        assert missing == []

    def test_recursive_basename_match_in_nested_subdir(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "deep" / "nested" / "a.jpg")
        found, missing = resolve_images(["a.jpg"], [tmp_path])
        assert found == {"a.jpg": img}
        assert missing == []

    def test_direct_match_wins_over_recursive_in_same_dir(self, tmp_path: Path) -> None:
        flat = _touch(tmp_path / "a.jpg")
        _touch(tmp_path / "nested" / "a.jpg")
        found, _ = resolve_images(["a.jpg"], [tmp_path])
        assert found["a.jpg"] == flat

    def test_earlier_search_dir_wins(self, tmp_path: Path) -> None:
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        nested = _touch(dir1 / "sub" / "a.jpg")
        _touch(dir2 / "a.jpg")
        found, _ = resolve_images(["a.jpg"], [dir1, dir2])
        assert found["a.jpg"] == nested

    def test_duplicate_basenames_pick_lexicographic_max_and_warn(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        _touch(tmp_path / "2026-01" / "a.jpg")
        latest = _touch(tmp_path / "2026-02" / "a.jpg")
        found, _ = resolve_images(["a.jpg"], [tmp_path])
        assert found["a.jpg"] == latest
        assert any("Дубликаты" in m for m in capture_logs)

    def test_missing_names_sorted(self, tmp_path: Path) -> None:
        _, missing = resolve_images(["b.jpg", "a.jpg"], [tmp_path])
        assert missing == ["a.jpg", "b.jpg"]

    def test_nonexistent_search_dir_skipped(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "real" / "a.jpg")
        found, missing = resolve_images(
            ["a.jpg"], [tmp_path / "nope", tmp_path / "real"]
        )
        assert found == {"a.jpg": img}
        assert missing == []


class TestBuildServerFileMapping:
    """Tests for build_server_file_mapping()."""

    def test_existing_flat_image_keeps_path(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/img1.jpg", "img1.jpg"),
                ("project/images/img2.jpg", "img2.jpg"),
            ]
        )

        mapping, existing_keys = build_server_file_mapping(
            cs_info,
            {"img1.jpg", "img2.jpg"},
            s3_client=s3,
        )

        assert mapping["img1.jpg"] == "img1.jpg"
        assert mapping["img2.jpg"] == "img2.jpg"
        assert existing_keys == {
            "project/images/img1.jpg",
            "project/images/img2.jpg",
        }

    def test_existing_subfolder_image_keeps_path(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/2026-01/img1.jpg", "2026-01/img1.jpg"),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"img1.jpg"},
            s3_client=s3,
        )

        assert mapping["img1.jpg"] == "2026-01/img1.jpg"

    def test_new_image_gets_month_prefix(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client([])

        mapping, existing_keys = build_server_file_mapping(
            cs_info,
            {"new_img.jpg"},
            s3_client=s3,
        )

        assert _MONTH_PREFIX_RE.fullmatch(mapping["new_img.jpg"])
        assert mapping["new_img.jpg"].endswith("/new_img.jpg")
        assert existing_keys == set()

    def test_mixed_existing_and_new(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/old.jpg", "old.jpg"),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"old.jpg", "brand_new.jpg"},
            s3_client=s3,
        )

        assert mapping["old.jpg"] == "old.jpg"
        assert _MONTH_PREFIX_RE.fullmatch(mapping["brand_new.jpg"])
        assert mapping["brand_new.jpg"].endswith("/brand_new.jpg")

    def test_duplicate_basenames_uses_latest(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/2026-01/img.jpg", "2026-01/img.jpg"),
                ("project/images/2026-02/img.jpg", "2026-02/img.jpg"),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"img.jpg"},
            s3_client=s3,
        )

        # Lexicographic max = 2026-02
        assert mapping["img.jpg"] == "2026-02/img.jpg"

    def test_deep_nested_subfolder(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                (
                    "project/images/subdir/another/img.jpg",
                    "subdir/another/img.jpg",
                ),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"img.jpg"},
            s3_client=s3,
        )

        assert mapping["img.jpg"] == "subdir/another/img.jpg"
        assert (
            build_s3_key(cs_info.prefix, mapping["img.jpg"])
            == "project/images/subdir/another/img.jpg"
        )

    def test_mixed_depths_with_prefix(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/flat.jpg", "flat.jpg"),
                ("project/images/2026-03/monthly.jpg", "2026-03/monthly.jpg"),
                ("project/images/a/b/c/deep.jpg", "a/b/c/deep.jpg"),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"flat.jpg", "monthly.jpg", "deep.jpg"},
            s3_client=s3,
        )

        assert mapping["flat.jpg"] == "flat.jpg"
        assert mapping["monthly.jpg"] == "2026-03/monthly.jpg"
        assert mapping["deep.jpg"] == "a/b/c/deep.jpg"

        # All produce correct full S3 keys
        assert (
            build_s3_key(cs_info.prefix, mapping["flat.jpg"])
            == "project/images/flat.jpg"
        )
        assert (
            build_s3_key(cs_info.prefix, mapping["monthly.jpg"])
            == "project/images/2026-03/monthly.jpg"
        )
        assert (
            build_s3_key(cs_info.prefix, mapping["deep.jpg"])
            == "project/images/a/b/c/deep.jpg"
        )

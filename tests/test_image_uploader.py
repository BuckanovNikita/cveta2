"""Tests for image_uploader module — server file mapping."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

from cveta2.image_downloader import CloudStorageInfo
from cveta2.image_uploader import build_server_file_mapping

_MONTH_PREFIX_RE = re.compile(r"\d{4}-\d{2}/.+")


def _make_cs_info(
    bucket: str = "test-bucket",
    prefix: str = "project/images",
) -> CloudStorageInfo:
    return CloudStorageInfo(
        id=1,
        bucket=bucket,
        prefix=prefix,
        endpoint_url="http://localhost:9000",
    )


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

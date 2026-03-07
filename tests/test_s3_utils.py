"""Tests for s3_utils — build_s3_key edge cases."""

from __future__ import annotations

from cveta2.s3_utils import build_s3_key


class TestBuildS3Key:
    """Tests for build_s3_key() prefix handling."""

    def test_prefix_prepended(self) -> None:
        assert build_s3_key("proj", "2026-03/img.jpg") == "proj/2026-03/img.jpg"

    def test_no_double_prefix(self) -> None:
        assert build_s3_key("proj", "proj/2026-03/img.jpg") == "proj/2026-03/img.jpg"

    def test_empty_prefix_passthrough(self) -> None:
        assert build_s3_key("", "2026-03/img.jpg") == "2026-03/img.jpg"

    def test_deep_nested_path(self) -> None:
        assert build_s3_key("proj", "a/b/c/img.jpg") == "proj/a/b/c/img.jpg"

    def test_flat_filename(self) -> None:
        assert build_s3_key("proj", "img.jpg") == "proj/img.jpg"

    def test_multi_segment_prefix(self) -> None:
        assert (
            build_s3_key("project/images", "2026-03/img.jpg")
            == "project/images/2026-03/img.jpg"
        )

    def test_multi_segment_prefix_no_double(self) -> None:
        assert (
            build_s3_key("project/images", "project/images/2026-03/img.jpg")
            == "project/images/2026-03/img.jpg"
        )

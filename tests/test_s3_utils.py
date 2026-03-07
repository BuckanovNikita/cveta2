"""Tests for s3_utils — build_s3_key edge cases."""

from __future__ import annotations

import pytest

from cveta2.s3_utils import build_s3_key


class TestBuildS3Key:
    """Tests for build_s3_key() prefix handling."""

    @pytest.mark.parametrize(
        ("prefix", "path", "expected"),
        [
            ("proj", "2026-03/img.jpg", "proj/2026-03/img.jpg"),
            ("proj", "proj/2026-03/img.jpg", "proj/2026-03/img.jpg"),
            ("", "2026-03/img.jpg", "2026-03/img.jpg"),
            ("proj", "a/b/c/img.jpg", "proj/a/b/c/img.jpg"),
            ("proj", "img.jpg", "proj/img.jpg"),
            ("project/images", "2026-03/img.jpg", "project/images/2026-03/img.jpg"),
            (
                "project/images",
                "project/images/2026-03/img.jpg",
                "project/images/2026-03/img.jpg",
            ),
        ],
        ids=[
            "prefix_prepended",
            "no_double_prefix",
            "empty_prefix_passthrough",
            "deep_nested_path",
            "flat_filename",
            "multi_segment_prefix",
            "multi_segment_prefix_no_double",
        ],
    )
    def test_build_s3_key(self, prefix: str, path: str, expected: str) -> None:
        assert build_s3_key(prefix, path) == expected

"""Tests for s3_utils — build_s3_key and parse_sync_root edge cases."""

from __future__ import annotations

import pytest

from cveta2.s3_utils import build_s3_key, parse_sync_root


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


class TestParseSyncRoot:
    """Tests for parse_sync_root() bucket/prefix parsing."""

    @pytest.mark.parametrize(
        ("root", "expected"),
        [
            ("s3://bucket/some/prefix", ("bucket", "some/prefix")),
            ("s3://bucket/some/prefix/", ("bucket", "some/prefix")),
            ("s3://bucket/images/my_favourite", ("bucket", "images/my_favourite")),
            ("s3://bucket", ("bucket", "")),
            ("s3://bucket/", ("bucket", "")),
            ("some/prefix", (None, "some/prefix")),
            ("some/prefix///", (None, "some/prefix")),
            ("prefix", (None, "prefix")),
            ("  s3://bucket/p  ", ("bucket", "p")),
        ],
        ids=[
            "url_with_prefix",
            "url_trailing_slash",
            "url_deep_prefix",
            "url_bucket_only",
            "url_bucket_only_trailing_slash",
            "bare_prefix",
            "bare_prefix_trailing_slashes",
            "bare_single_segment",
            "surrounding_whitespace",
        ],
    )
    def test_valid_roots(self, root: str, expected: tuple[str | None, str]) -> None:
        assert parse_sync_root(root) == expected

    @pytest.mark.parametrize(
        "root",
        ["", "   ", "s3://", "s3:///some/prefix", "///"],
        ids=["empty", "whitespace", "no_bucket", "empty_bucket", "only_slashes"],
    )
    def test_invalid_roots(self, root: str) -> None:
        with pytest.raises(ValueError, match="sync root"):
            parse_sync_root(root)

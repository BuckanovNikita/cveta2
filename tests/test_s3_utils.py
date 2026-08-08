"""Tests for s3_utils — key algebra, duplicate resolution and S3 listing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from cveta2.s3_utils import (
    build_s3_key,
    list_s3_objects,
    make_s3_client,
    names_with_basename_fallback,
    parse_sync_root,
    pick_latest_duplicate,
    run_s3_transfers,
    set_default_data_timeout,
    strip_key_prefix,
)
from tests.fixtures.fake_s3 import PagedFakeS3Client

if TYPE_CHECKING:
    from collections.abc import Generator


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
            ("data/proj1", "proj10/img.jpg", "data/proj1/proj10/img.jpg"),
            ("data/proj1", "data/proj10/img.jpg", "data/proj1/data/proj10/img.jpg"),
            ("proj/", "img.jpg", "proj/img.jpg"),
        ],
        ids=[
            "prefix_prepended",
            "no_double_prefix",
            "empty_prefix_passthrough",
            "deep_nested_path",
            "flat_filename",
            "multi_segment_prefix",
            "multi_segment_prefix_no_double",
            "sibling_named_like_the_prefix",
            "sibling_key_is_not_already_prefixed",
            "configured_trailing_slash_does_not_double",
        ],
    )
    def test_build_s3_key(self, prefix: str, path: str, expected: str) -> None:
        assert build_s3_key(prefix, path) == expected

    def test_a_prefix_may_end_in_any_character(self) -> None:
        """``rstrip`` takes a character *set*, so only the slash may come off.

        Every other prefix here ends in a lowercase letter or a digit that no
        plausible mutation of ``"/"`` also contains.
        """
        assert build_s3_key("dataX", "img.jpg") == "dataX/img.jpg"

    @pytest.mark.parametrize(
        ("prefix", "name"),
        [
            ("data/proj1", "img.jpg"),
            ("data/proj1", "2026-03/img.jpg"),
            ("data/proj1", "proj10/img.jpg"),
            ("proj/", "img.jpg"),
            ("", "img.jpg"),
        ],
    )
    def test_key_round_trips_back_to_the_frame_name(
        self, prefix: str, name: str
    ) -> None:
        """The two helpers are inverses — including across a sibling prefix.

        ``build_s3_key`` used to skip the join whenever the frame name merely
        *started with* the prefix string, and ``strip_key_prefix`` used to cut
        that many characters off regardless of where the folder boundary was.
        With ``prefix="data/proj1"``, a ``proj10/`` frame therefore came back
        as ``0/img.jpg``.
        """
        assert strip_key_prefix(build_s3_key(prefix, name), prefix) == name


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
        ("root", "expected"),
        [("s3://bucket/imagesX/", ("bucket", "imagesX")), ("dataX//", (None, "dataX"))],
        ids=["url", "bare"],
    )
    def test_only_slashes_are_stripped_from_the_tail(
        self, root: str, expected: tuple[str | None, str]
    ) -> None:
        """``rstrip`` takes a character *set*, so a prefix may end in any letter.

        Every previous case ended in a slash-preceded lowercase name, which
        cannot tell ``rstrip("/")`` apart from stripping a wider set.
        """
        assert parse_sync_root(root) == expected

    @pytest.mark.parametrize(
        "root",
        ["", "   ", "s3://", "s3:///some/prefix", "///"],
        ids=["empty", "whitespace", "no_bucket", "empty_bucket", "only_slashes"],
    )
    def test_invalid_roots(self, root: str) -> None:
        with pytest.raises(ValueError, match="sync root"):
            parse_sync_root(root)


class TestStripKeyPrefix:
    """Tests for strip_key_prefix() subfolder-preserving stripping."""

    @pytest.mark.parametrize(
        ("key", "prefix", "expected"),
        [
            ("data/projA/2026-01/img.jpg", "data/projA", "2026-01/img.jpg"),
            ("data/projA/img.jpg", "data/projA", "img.jpg"),
            ("data/projA/a/b/img.jpg", "data", "projA/a/b/img.jpg"),
            ("data/projA/img.jpg", "", "data/projA/img.jpg"),
            ("other/img.jpg", "data/projA", "other/img.jpg"),
            ("data/projA/img.jpg", "data/projA/", "img.jpg"),
            ("data/proj10/img.jpg", "data/proj1", "data/proj10/img.jpg"),
            ("data/projA", "data/projA", ""),
            ("data/projA/", "data/projA", ""),
        ],
        ids=[
            "keeps_subfolders",
            "single_level",
            "partial_prefix",
            "empty_prefix",
            "unrelated_prefix_unchanged",
            "trailing_slash_prefix",
            "sibling_prefix_is_not_a_match",
            "folder_marker_strips_to_empty",
            "folder_marker_with_slash_strips_to_empty",
        ],
    )
    def test_strip_key_prefix(self, key: str, prefix: str, expected: str) -> None:
        assert strip_key_prefix(key, prefix) == expected

    def test_only_the_separator_is_stripped_from_the_head(self) -> None:
        """The slice cuts exactly the prefix, so the first letter must survive.

        Every other case has a remainder starting with a lowercase letter or a
        digit, which cannot tell an exact cut apart from stripping more.
        """
        assert strip_key_prefix("data/Xmas.jpg", "data") == "Xmas.jpg"

    def test_a_doubled_separator_in_the_key_is_left_alone(self) -> None:
        """``a//b`` and ``a/b`` are different S3 objects and stay different.

        Collapsing the second slash would map both onto one local file.
        """
        assert strip_key_prefix("data//img.jpg", "data") == "/img.jpg"


@pytest.fixture
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    yield
    set_default_data_timeout(None)


@pytest.mark.usefixtures("_aws_env")
def test_default_data_timeout_reaches_the_client() -> None:
    """The setter's only observable effect is the client it later configures.

    Asserting it here, next to a bare ``make_s3_client()``, keeps the check
    cheap: nothing else has to be constructed to see the stored value.
    """
    set_default_data_timeout(7.0)
    client: Any = make_s3_client()
    assert client.meta.config.read_timeout == 7.0


class TestRunS3Transfers:
    """Tests for run_s3_transfers() success/failure accounting."""

    def test_counts_each_outcome_separately(self) -> None:
        """Two of each outcome: a single one cannot tell ``+= 1`` from ``= 1``.

        Recording the items also pins that *transfer* receives the item
        itself rather than a placeholder.
        """
        seen: list[str] = []

        def transfer(item: str) -> None:
            seen.append(item)
            if item.startswith("bad"):
                raise OSError(item)

        ok, failed = run_s3_transfers(
            ["good1", "bad1", "good2", "bad2"],
            transfer,
            str,
            desc="Загрузка",
            unit="файл",
        )

        assert (ok, failed) == (2, 2)
        assert seen == ["good1", "bad1", "good2", "bad2"]

    def test_progress_bar_carries_the_callers_labels(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """*desc* and *unit* exist only to label the bar, so only it can show them.

        Dropping either argument leaves the counts untouched and shows the
        user a bar titled with tqdm's generic defaults instead.
        """
        run_s3_transfers(["a"], lambda _item: None, str, desc="Скачивание", unit="кадр")

        bar = capsys.readouterr().err
        assert "Скачивание" in bar
        assert "кадр" in bar

    @pytest.mark.parametrize(
        "error",
        [OSError("boom"), ConnectionError("boom"), KeyError("Body")],
        ids=["os", "connection", "key"],
    )
    def test_transport_failures_are_absorbed(self, error: Exception) -> None:
        """Every member of S3_TRANSFER_ERRORS keeps the remaining items going."""

        def transfer(item: str) -> None:
            if item == "bad":
                raise error

        ok, failed = run_s3_transfers(
            ["bad", "good"], transfer, str, desc="d", unit="u"
        )

        assert (ok, failed) == (1, 1)

    def test_unexpected_error_aborts_the_run(self) -> None:
        """A programming error must not be swallowed as a failed transfer."""

        def transfer(item: str) -> None:
            raise ValueError(item)

        with pytest.raises(ValueError, match="a"):
            run_s3_transfers(["a"], transfer, str, desc="d", unit="u")


class TestPickLatestDuplicate:
    """Tests for pick_latest_duplicate() winner choice and duplicate warning."""

    def test_lexicographic_max_wins(self) -> None:
        candidates = ["2026-01/img.jpg", "2026-03/img.jpg", "2026-02/img.jpg"]
        assert pick_latest_duplicate("S3", "img.jpg", candidates) == "2026-03/img.jpg"

    def test_ordering_is_lexicographic_not_natural(self) -> None:
        """``key=str`` is load-bearing: "9" sorts after "10", 9 does not after 10.

        Path and str candidates order identically with and without the key,
        so only a value whose natural order differs from its text order can
        show that the key is applied at all.
        """
        assert pick_latest_duplicate("S3", "img.jpg", [9, 10]) == 9

    def test_single_candidate_is_not_reported_as_a_duplicate(
        self, capture_logs: list[str]
    ) -> None:
        """The warning is the whole point of the branch, so its absence counts."""
        assert pick_latest_duplicate("S3", "img.jpg", ["2026-01/img.jpg"]) == (
            "2026-01/img.jpg"
        )
        assert capture_logs == []

    def test_two_candidates_warn_once(self, capture_logs: list[str]) -> None:
        """Two is already a duplicate; nothing else observes the branch."""
        pick_latest_duplicate("S3", "img.jpg", ["2026-01/img.jpg", "2026-02/img.jpg"])
        assert len(capture_logs) == 1


class TestNamesWithBasenameFallback:
    """Tests for names_with_basename_fallback() aliasing rules."""

    def test_nested_name_is_also_reachable_by_basename(self) -> None:
        result = names_with_basename_fallback([("2026-02/img.jpg", "key-a")])
        assert result == {"2026-02/img.jpg": "key-a", "img.jpg": "key-a"}

    def test_real_name_wins_over_a_later_basename_alias(self) -> None:
        """An explicit flat name must not be overwritten by an alias behind it."""
        result = names_with_basename_fallback(
            [("img.jpg", "flat"), ("2026-02/img.jpg", "nested")]
        )
        assert result["img.jpg"] == "flat"
        assert result["2026-02/img.jpg"] == "nested"

    def test_first_alias_wins(self) -> None:
        result = names_with_basename_fallback(
            [("2026-01/img.jpg", "old"), ("2026-02/img.jpg", "new")]
        )
        assert result["img.jpg"] == "old"


class TestListS3Objects:
    """Tests for list_s3_objects() request shape and pagination."""

    def test_follows_the_continuation_token_to_the_next_page(self) -> None:
        """The truncated tail was dead code: one-page fakes never reach it."""
        s3 = PagedFakeS3Client(
            [["images/a.jpg", "images/b.jpg"], ["images/c.jpg"]],
            bucket="test-bucket",
        )

        result = list_s3_objects(s3, "test-bucket", "images")

        assert result == [
            ("images/a.jpg", "a.jpg"),
            ("images/b.jpg", "b.jpg"),
            ("images/c.jpg", "c.jpg"),
        ]
        assert [call.get("ContinuationToken") for call in s3.list_calls] == [None, "1"]

    def test_bucket_and_prefix_are_sent_under_their_s3_names(self) -> None:
        """The listing is filtered server-side, so the parameter names matter."""
        s3 = PagedFakeS3Client([["images/a.jpg", "other/b.jpg"]])

        result = list_s3_objects(s3, "test-bucket", "images")

        assert result == [("images/a.jpg", "a.jpg")]
        assert s3.list_calls == [{"Bucket": "test-bucket", "Prefix": "images/"}]

    def test_the_server_side_filter_excludes_sibling_prefixes(self) -> None:
        """``Prefix`` is a raw substring to S3, so the trailing slash matters.

        Listing ``data/proj1`` without it also returns every ``data/proj10/``
        key, which then reaches the name map, the local cache layout and
        upload's existing-key set as a mangled ``0/...`` name.
        """
        s3 = PagedFakeS3Client([["data/proj1/a.jpg", "data/proj10/b.jpg"]])

        assert list_s3_objects(s3, "test-bucket", "data/proj1") == [
            ("data/proj1/a.jpg", "a.jpg")
        ]
        assert s3.list_calls == [{"Bucket": "test-bucket", "Prefix": "data/proj1/"}]

    def test_empty_listing_omits_the_contents_key(self) -> None:
        """S3 drops ``Contents`` from an empty page instead of sending ``[]``."""
        s3 = PagedFakeS3Client([[]])
        assert list_s3_objects(s3, "test-bucket", "images") == []

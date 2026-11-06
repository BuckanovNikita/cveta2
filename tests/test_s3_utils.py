"""Tests for s3_utils — key algebra, duplicate resolution and S3 listing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import (
    ConnectionClosedError,
    EndpointConnectionError,
    IncompleteReadError,
)

from cveta2.adapters.execution.concurrency import Workers, configure_workers
from cveta2.adapters.execution.retry import RetryPolicy, configure_retries
from cveta2.adapters.s3.utils import (
    list_s3_objects,
    make_s3_client,
    run_s3_transfers,
    s3_get_bytes,
    set_default_data_timeout,
)
from cveta2.domain.paths import (
    build_s3_key,
    names_with_basename_fallback,
    parse_sync_root,
    pick_latest_duplicate,
    strip_key_prefix,
)
from tests.fixtures.fake_s3 import FakeS3Client, PagedFakeS3Client

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
            # ``rstrip`` takes a character *set*, so only the slash may come off.
            ("dataX", "img.jpg", "dataX/img.jpg"),
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
            "prefix_may_end_in_any_character",
        ],
    )
    def test_build_s3_key(self, prefix: str, path: str, expected: str) -> None:
        assert build_s3_key(prefix, path) == expected

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
            # ``rstrip`` takes a character *set*: only slashes leave the tail.
            ("s3://bucket/imagesX/", ("bucket", "imagesX")),
            ("dataX//", (None, "dataX")),
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
            "url_tail_ends_in_any_letter",
            "bare_tail_ends_in_any_letter",
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
            # The slice cuts exactly the prefix, so the first letter survives.
            ("data/Xmas.jpg", "data", "Xmas.jpg"),
            # ``a//b`` and ``a/b`` are different objects and stay different.
            ("data//img.jpg", "data", "/img.jpg"),
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
            "only_the_separator_leaves_the_head",
            "doubled_separator_is_left_alone",
        ],
    )
    def test_strip_key_prefix(self, key: str, prefix: str, expected: str) -> None:
        assert strip_key_prefix(key, prefix) == expected


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
        [
            OSError("boom"),
            ConnectionError("boom"),
            KeyError("Body"),
            IncompleteReadError(actual_bytes=1, expected_bytes=2),
            EndpointConnectionError(endpoint_url="http://x"),
            ConnectionClosedError(endpoint_url="http://x"),
        ],
        ids=["os", "connection", "key", "incomplete-read", "endpoint", "closed"],
    )
    def test_transport_failures_are_absorbed(self, error: Exception) -> None:
        """Every member of S3_TRANSFER_ERRORS keeps the remaining items going.

        The botocore faults are ``BotoCoreError`` only, not ``OSError``:
        a connection dropped mid-body used to escape the batch entirely.
        """

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


class _BodyDroppedOnce:
    """Streaming body whose first ``read`` dies the way a cut connection does."""

    def __init__(self) -> None:
        self.reads = 0

    def read(self) -> bytes:
        self.reads += 1
        if self.reads == 1:
            raise IncompleteReadError(actual_bytes=1, expected_bytes=2)
        return b"data"


def test_get_bytes_retries_a_body_dropped_mid_read() -> None:
    """A body cut mid-read is the fault botocore's own retries cannot see.

    ``get_object`` has already returned by then, so only ``s3_retry`` can
    repeat the read.
    """
    previous = (RetryPolicy.attempts, RetryPolicy.max_wait)
    configure_retries(3, 0.01)
    body = _BodyDroppedOnce()
    client = MagicMock()
    client.get_object.return_value = {"Body": body}

    try:
        assert s3_get_bytes(client, "bkt", "key") == b"data"
        assert body.reads == 2
    finally:
        configure_retries(*previous)


@pytest.mark.parametrize(
    ("candidates", "expected", "warnings"),
    [
        pytest.param(
            ["2026-01/img.jpg", "2026-03/img.jpg", "2026-02/img.jpg"],
            "2026-03/img.jpg",
            1,
            id="lexicographic-max",
        ),
        # "9" sorts after "10" as text but not as a number.
        pytest.param([9, 10], 9, 1, id="text-not-natural-order"),
        pytest.param(["2026-01/img.jpg"], "2026-01/img.jpg", 0, id="single-no-warning"),
    ],
)
def test_pick_latest_duplicate(
    capture_logs: list[str], candidates: list[object], expected: object, warnings: int
) -> None:
    assert pick_latest_duplicate("S3", "img.jpg", candidates) == expected
    assert len(capture_logs) == warnings


@pytest.mark.parametrize(
    ("pairs", "expected"),
    [
        pytest.param(
            [("2026-02/img.jpg", "key-a")],
            {"2026-02/img.jpg": "key-a", "img.jpg": "key-a"},
            id="nested-reachable-by-basename",
        ),
        # An explicit flat name is not overwritten by an alias behind it.
        pytest.param(
            [("img.jpg", "flat"), ("2026-02/img.jpg", "nested")],
            {"img.jpg": "flat", "2026-02/img.jpg": "nested"},
            id="real-name-wins",
        ),
        pytest.param(
            [("2026-01/img.jpg", "old"), ("2026-02/img.jpg", "new")],
            {"2026-01/img.jpg": "old", "2026-02/img.jpg": "new", "img.jpg": "old"},
            id="first-alias-wins",
        ),
    ],
)
def test_names_with_basename_fallback(
    pairs: list[tuple[str, str]], expected: dict[str, str]
) -> None:
    assert names_with_basename_fallback(pairs) == expected


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

    @pytest.mark.parametrize(
        ("keys", "prefix", "expected"),
        [
            pytest.param(
                ["images/a.jpg", "other/b.jpg"],
                "images",
                ("images/a.jpg", "a.jpg"),
                id="bucket-and-prefix",
            ),
            # ``Prefix`` is a raw substring to S3, so without the trailing
            # slash ``data/proj1`` would also return every ``data/proj10/`` key.
            pytest.param(
                ["data/proj1/a.jpg", "data/proj10/b.jpg"],
                "data/proj1",
                ("data/proj1/a.jpg", "a.jpg"),
                id="sibling-prefix-excluded",
            ),
        ],
    )
    def test_the_listing_is_filtered_server_side(
        self, keys: list[str], prefix: str, expected: tuple[str, str]
    ) -> None:
        """Bucket and prefix are sent under their S3 parameter names."""
        s3 = PagedFakeS3Client([keys])

        assert list_s3_objects(s3, "test-bucket", prefix) == [expected]
        assert s3.list_calls == [{"Bucket": "test-bucket", "Prefix": f"{prefix}/"}]

    def test_empty_listing_omits_the_contents_key(self) -> None:
        """S3 drops ``Contents`` from an empty page instead of sending ``[]``."""
        s3 = PagedFakeS3Client([[]])
        assert list_s3_objects(s3, "test-bucket", "images") == []

    @pytest.mark.parametrize(
        ("objects", "prefix", "expected"),
        [
            pytest.param(
                {"images/a.jpg": b"a", "images/b.jpg": b"b"},
                "images",
                [("images/a.jpg", "a.jpg"), ("images/b.jpg", "b.jpg")],
                id="relative-to-prefix",
            ),
            pytest.param(
                {"cat.jpg": b"cat", "dog.jpg": b"dog"},
                "",
                [("cat.jpg", "cat.jpg"), ("dog.jpg", "dog.jpg")],
                id="empty-prefix-keeps-full-names",
            ),
            pytest.param(
                {"images/": b"", "images/a.jpg": b"a"},
                "images",
                [("images/a.jpg", "a.jpg")],
                id="folder-marker-skipped",
            ),
        ],
    )
    def test_names(
        self, objects: dict[str, bytes], prefix: str, expected: list[tuple[str, str]]
    ) -> None:
        s3 = FakeS3Client(objects, keyed_by_bucket=False)
        assert list_s3_objects(s3, "test-bucket", prefix) == expected


# ---------------------------------------------------------------------------
# parallel prefix listing
# ---------------------------------------------------------------------------


_LISTING_OBJECTS = {
    "bucket/data/proj/2026-01/a.jpg": b"a",
    "bucket/data/proj/2026-01/b.jpg": b"b",
    "bucket/data/proj/2026-02/c.jpg": b"c",
    "bucket/data/proj/2026-03/d.jpg": b"d",
    "bucket/data/proj/loose.jpg": b"e",
    "bucket/data/proj/nested/deep/f.jpg": b"f",
}


@pytest.fixture
def _listing_workers() -> Generator[None, None, None]:
    s3, cvat = Workers.s3, Workers.cvat
    yield
    configure_workers(s3=s3, cvat=cvat)


@pytest.mark.usefixtures("_listing_workers")
def test_parallel_listing_matches_the_sequential_one_exactly() -> None:
    """Fanning out by subfolder must not change the result in any way.

    Callers depend on the order — ``names_with_basename_fallback`` keeps
    the *first* entry for a duplicate basename — so completion order
    leaking through would silently repoint images at different keys.
    """
    client = FakeS3Client(dict(_LISTING_OBJECTS), keyed_by_bucket=True)

    configure_workers(s3=1, cvat=1)
    sequential = list_s3_objects(client, "bucket", "data/proj")

    configure_workers(s3=8, cvat=1)
    parallel = list_s3_objects(client, "bucket", "data/proj")

    assert parallel == sequential
    assert sequential == sorted(sequential, key=lambda pair: pair[0])
    # Keys directly under the prefix belong to no subfolder and are only
    # reachable from the delimiter pass.
    assert len(sequential) == len(_LISTING_OBJECTS)


@pytest.mark.parametrize("workers", [2, 8])
@pytest.mark.usefixtures("_listing_workers")
def test_the_fan_out_really_pages_each_subfolder_separately(workers: int) -> None:
    """Without the delimiter pass this silently stays one serial chain.

    The result is identical either way, so only the call pattern shows
    whether the work was actually split.  Two workers already fan out.
    """
    client = FakeS3Client(dict(_LISTING_OBJECTS), keyed_by_bucket=True)

    configure_workers(s3=1, cvat=1)
    list_s3_objects(client, "bucket", "data/proj")
    serial_calls = len(client.list_requests)

    client.list_requests.clear()
    configure_workers(s3=workers, cvat=1)
    list_s3_objects(client, "bucket", "data/proj")

    subfolders = {"2026-01/", "2026-02/", "2026-03/", "nested/"}
    assert serial_calls == 1
    assert len(client.list_requests) == 1 + len(subfolders)
    assert {call.get("Prefix", "") for call in client.list_requests} == {
        "data/proj/",
        *(f"data/proj/{folder}" for folder in subfolders),
    }


@pytest.mark.usefixtures("_listing_workers")
def test_the_listing_targets_the_requested_bucket() -> None:
    """Every page — delimiter pass and subfolder pass alike — needs the bucket."""
    client = FakeS3Client(dict(_LISTING_OBJECTS), keyed_by_bucket=True)
    configure_workers(s3=8, cvat=1)

    assert list_s3_objects(client, "other-bucket", "data/proj") == []
    assert all(call.get("Bucket") == "other-bucket" for call in client.list_requests)


@pytest.mark.usefixtures("_listing_workers")
def test_a_storage_with_no_subfolders_still_lists() -> None:
    """The fan-out has nothing to split, so it falls back to one pass."""
    client = FakeS3Client(
        {"bucket/data/proj/a.jpg": b"a", "bucket/data/proj/b.jpg": b"b"},
        keyed_by_bucket=True,
    )
    configure_workers(s3=8, cvat=1)

    assert [name for _, name in list_s3_objects(client, "bucket", "data/proj")] == [
        "a.jpg",
        "b.jpg",
    ]


@pytest.mark.usefixtures("_listing_workers")
def test_a_failed_subfolder_listing_aborts_the_whole_listing() -> None:
    """A partial listing is worse than no listing.

    Every caller treats "not in the listing" as "not on S3": the uploader
    would re-upload the objects it could not see, and the downloader would
    report them missing. Both are silent, so the failure has to surface.
    """

    class _FlakyListing(FakeS3Client):
        def list_objects_v2(self, **kwargs: str) -> dict[str, Any]:
            if kwargs.get("Prefix", "").endswith("2026-02/"):
                raise OSError("listing failed")
            return super().list_objects_v2(**kwargs)

    client = _FlakyListing(dict(_LISTING_OBJECTS), keyed_by_bucket=True)
    configure_workers(s3=8, cvat=1)

    with pytest.raises(OSError, match="listing failed"):
        list_s3_objects(client, "bucket", "data/proj")

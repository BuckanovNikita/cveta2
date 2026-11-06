"""Image requests abort, while interrupted bodies and local writes are counted."""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    IncompleteReadError,
    NoCredentialsError,
)

from cveta2.adapters.execution.retry import RetryPolicy, configure_retries
from cveta2.adapters.s3.download import ImageDownloader
from cveta2.domain.models import ProjectAnnotations
from cveta2.domain.storage import DownloadStats
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import make_bbox, make_cs_info

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def short_retries() -> Iterator[None]:
    previous = RetryPolicy.attempts, RetryPolicy.max_wait
    configure_retries(2, 0)
    try:
        yield
    finally:
        configure_retries(*previous)


def _download_a(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch, client: FakeS3Client
) -> DownloadStats:
    """Download the single frame ``a.jpg`` from ``bucket/images`` via *client*."""
    monkeypatch.setattr("cveta2.adapters.s3.download.make_s3_client", lambda _: client)
    return ImageDownloader(tmp_path).download(
        ProjectAnnotations(
            annotations=[make_bbox(image_name="a.jpg")], deleted_images=[]
        ),
        make_cs_info(bucket="bucket", prefix="images"),
    )


class _FailingRequest(FakeS3Client):
    def __init__(self, error: Exception) -> None:
        super().__init__({"bucket/images/a.jpg": b"data"})
        self.error = error
        self.attempts = 0

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.get_calls.append(f"{Bucket}/{Key}")
        self.attempts += 1
        raise self.error


@pytest.mark.parametrize("listing_first", [False, True])
@pytest.mark.parametrize(
    ("error", "attempts"),
    [
        (ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject"), 1),
        (NoCredentialsError(), 1),
        (EndpointConnectionError(endpoint_url="https://storage.invalid"), 2),
        (OSError("request connection failed"), 2),
        (ClientError({"Error": {"Code": "InternalError"}}, "GetObject"), 2),
        # Without an error payload the original failure still surfaces.
        (ClientError({}, "GetObject"), 1),
    ],
)
def test_request_failures_abort_without_missing_fallback(
    tmp_path: "Path",
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    attempts: int,
    *,
    listing_first: bool,
) -> None:
    client = _FailingRequest(error)
    if listing_first:
        monkeypatch.setattr("cveta2.adapters.s3.download._DIRECT_KEY_PROBE_LIMIT", 0)
    with pytest.raises(type(error)) as caught:
        _download_a(tmp_path, monkeypatch, client)
    assert caught.value is error
    assert client.attempts == attempts
    assert len(client.list_requests) == int(listing_first)
    assert client.head_calls == []
    assert not (tmp_path / "a.jpg").exists()


class _BrokenBody:
    def read(self) -> bytes:
        raise IncompleteReadError(actual_bytes=1, expected_bytes=10)


class _BodyFailure(FakeS3Client):
    def __init__(self, *, recover: bool) -> None:
        super().__init__({"bucket/images/a.jpg": b"complete"})
        self.recover = recover
        self.attempts = 0

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.attempts += 1
        if self.recover and self.attempts > 1:
            return super().get_object(Bucket=Bucket, Key=Key)
        return {"Body": _BrokenBody()}


@pytest.mark.parametrize("recover", [False, True])
def test_body_failures_retry_and_never_trigger_missing_fallback(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch, *, recover: bool
) -> None:
    client = _BodyFailure(recover=recover)
    result = _download_a(tmp_path, monkeypatch, client)
    assert client.attempts == 2
    assert client.list_requests == []
    assert client.head_calls == []
    assert result.total == 1
    assert result.downloaded == int(recover)
    assert result.failed == int(not recover)
    if recover:
        assert (tmp_path / "a.jpg").read_bytes() == b"complete"
    else:
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("code", ["NoSuchKey", "NotFound", "404"])
def test_only_missing_key_responses_trigger_listing(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    client = _FailingRequest(ClientError({"Error": {"Code": code}}, "GetObject"))
    client.objects.clear()
    stats = _download_a(tmp_path, monkeypatch, client)
    assert client.attempts == 1
    assert len(client.list_requests) == 1
    assert stats.failed == stats.total == 1


@pytest.mark.parametrize("listing_first", [False, True])
def test_object_disappearing_after_listing_counts_once(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch, *, listing_first: bool
) -> None:
    client = _FailingRequest(ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject"))
    if listing_first:
        monkeypatch.setattr("cveta2.adapters.s3.download._DIRECT_KEY_PROBE_LIMIT", 0)
    stats = _download_a(tmp_path, monkeypatch, client)
    assert stats.failed == stats.total == 1
    assert stats.downloaded == stats.cached == 0
    assert len(client.list_requests) == 1
    assert client.attempts == (1 if listing_first else 2)


def test_missing_code_during_body_read_is_not_a_missing_key(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailedBody:
        def read(self) -> bytes:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "Body")

    class FailedBodyClient(FakeS3Client):
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
            self.get_calls.append(f"{Bucket}/{Key}")
            return {"Body": FailedBody()}

    client = FailedBodyClient()
    stats = _download_a(tmp_path, monkeypatch, client)
    assert stats.failed == 1
    assert len(client.get_calls) == 1
    assert client.list_requests == []


def test_direct_failures_missing_keys_and_fallback_failures_accumulate(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]
) -> None:
    """Every failure kind adds to ``failed``; the rest still download.

    The failure log names each broken transfer by frame and key.
    """

    class MixedClient(FakeS3Client):
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
            if Key in {"images/broken1.jpg", "images/broken2.jpg"}:
                return {"Body": _BrokenBody()}
            if Key == "images/nested/vanish.jpg":
                raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
            return super().get_object(Bucket=Bucket, Key=Key)

    client = MixedClient(
        {
            f"bucket/images/{name}": b"image"
            for name in [
                "broken1.jpg",
                "broken2.jpg",
                "nested/vanish.jpg",
                "nested/good.jpg",
            ]
        }
    )
    monkeypatch.setattr("cveta2.adapters.s3.download.make_s3_client", lambda _: client)
    annotations = ProjectAnnotations(
        annotations=[
            make_bbox(image_name=name)
            for name in [
                "broken1.jpg",
                "broken2.jpg",
                "missing.jpg",
                "vanish.jpg",
                "good.jpg",
            ]
        ],
        deleted_images=[],
    )
    stats = ImageDownloader(tmp_path).download(
        annotations, make_cs_info(bucket="bucket", prefix="images")
    )
    assert (stats.total, stats.downloaded, stats.failed, stats.cached) == (5, 1, 4, 0)
    assert (tmp_path / "nested/good.jpg").read_bytes() == b"image"
    assert annotations.annotations[0].s3_image_path == "images/broken1.jpg"
    assert annotations.annotations[1].s3_image_path == "images/broken2.jpg"
    assert annotations.annotations[2].s3_image_path is None
    assert "broken1.jpg (key=images/broken1.jpg)" in "\n".join(capture_logs)


def test_listing_full_canonical_key_precedes_basename_fallback(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeS3Client(
        {
            "bucket/images/alpha/a.jpg": b"decoy",
            "bucket/images/images/nested/a.jpg": b"correct",
        }
    )
    monkeypatch.setattr("cveta2.adapters.s3.download.make_s3_client", lambda _: client)
    annotations = ProjectAnnotations(
        annotations=[make_bbox(image_name="a.jpg", frame_path="nested/a.jpg")],
        deleted_images=[],
    )
    stats = ImageDownloader(tmp_path).download(
        annotations, make_cs_info(bucket="bucket", prefix="images")
    )
    assert stats.downloaded == 1
    assert annotations.annotations[0].s3_image_path == "images/images/nested/a.jpg"
    assert (tmp_path / "images/nested/a.jpg").read_bytes() == b"correct"

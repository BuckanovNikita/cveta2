"""Capture S3 annotation CSV objects without any image transfers."""

import hashlib
from collections.abc import Callable
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from pydantic import ValidationError

from cveta2.adapters.s3.errors import S3_FAILURES
from cveta2.adapters.s3.types import S3Client
from cveta2.adapters.s3.utils import S3_TRANSFER_ERRORS, make_s3_client, s3_retry
from cveta2.application.ports.managed_sources import S3Object, S3ObjectIdentity
from cveta2.domain.managed.models import ManagedError, SourceDefinition


class _Body(Protocol):
    def read(self) -> bytes: ...
    def close(self) -> None: ...


def _identity(response: dict[str, Any]) -> S3ObjectIdentity:
    """Read ETag and VersionId the same way from a GET and a HEAD response."""
    return S3ObjectIdentity(
        etag=value if isinstance(value := response.get("ETag"), str) else None,
        version_id=value if isinstance(value := response.get("VersionId"), str) else None,
    )


class S3CsvSources:
    """Use the normal S3 credential chain and explicitly injected endpoint."""

    def __init__(self, client: S3Client | None = None, *, endpoint_url: str | None = None) -> None:
        """Defer client creation until an S3 source is actually requested."""
        self._client = client
        self._endpoint_url = endpoint_url

    def _s3(self) -> S3Client:
        if self._client is None:
            self._client = make_s3_client(self._endpoint_url)
        return self._client

    @s3_retry
    def _capture(self, bucket: str, key: str) -> S3Object:
        response = self._s3().get_object(Bucket=bucket, Key=key)
        # The optional backend's streaming body is opaque; its narrow protocol
        # describes the external SDK contract without leaking that type inward.
        body = cast("_Body", response["Body"])
        try:
            content = body.read()
        finally:
            body.close()
        if not isinstance(content, bytes):
            raise ManagedError("S3 returned a non-byte CSV body")
        identity = _identity(response)
        return S3Object(
            content=content,
            content_hash=hashlib.sha256(content).hexdigest(),
            etag=identity.etag,
            version_id=identity.version_id,
        )

    @s3_retry
    def _head(self, bucket: str, key: str) -> S3ObjectIdentity:
        return _identity(self._s3().head_object(Bucket=bucket, Key=key))

    def read_object(self, uri: str) -> S3Object:
        """Capture one complete object or raise an actionable managed error."""
        return _on_object(uri, self._capture)

    def object_identity(self, uri: str) -> S3ObjectIdentity:
        """Read the object's ETag and version ID with a HEAD request; the body is never read."""
        return _on_object(uri, self._head)


def _on_object[T](uri: str, operation: Callable[[str, str], T]) -> T:
    """Run *operation* on the bucket and key of an S3 CSV source, naming the source on failure.

    An invalid URI is refused without its value: one read from a hand-edited
    ``source-snapshot.yaml`` may carry credentials.
    """
    try:
        SourceDefinition(name="object", type="s3-csv", uri=uri)
        parts = urlsplit(uri)
        return operation(parts.netloc, parts.path.removeprefix("/"))
    except ValidationError:
        raise ManagedError("Invalid S3 CSV source uri: expected s3://bucket/key.csv") from None
    except (*S3_TRANSFER_ERRORS, *S3_FAILURES, AttributeError, TypeError) as error:
        raise ManagedError(f"Cannot read required S3 CSV source: {uri}") from error

"""Capture S3 annotation CSV objects without any image transfers."""

import hashlib
from typing import Protocol, cast
from urllib.parse import urlsplit

from cveta2.adapters.s3.types import S3Client
from cveta2.adapters.s3.utils import S3_TRANSFER_ERRORS, make_s3_client, s3_retry
from cveta2.application.ports.managed_sources import S3Object
from cveta2.domain.managed.models import ManagedError, SourceDefinition


class _Body(Protocol):
    def read(self) -> bytes: ...
    def close(self) -> None: ...


class S3CsvSources:
    """Use the normal S3 credential chain and explicitly injected endpoint."""

    def __init__(self, client: S3Client | None = None, *, endpoint_url: str | None = None) -> None:
        """Defer client creation until an S3 source is actually requested."""
        self._client = client
        self._endpoint_url = endpoint_url

    @s3_retry
    def _capture(self, bucket: str, key: str) -> S3Object:
        if self._client is None:
            self._client = make_s3_client(self._endpoint_url)
        response = self._client.get_object(Bucket=bucket, Key=key)
        # The optional backend's streaming body is opaque; its narrow protocol
        # describes the external SDK contract without leaking that type inward.
        body = cast("_Body", response["Body"])
        try:
            content = body.read()
        finally:
            body.close()
        if not isinstance(content, bytes):
            raise ManagedError("S3 returned a non-byte CSV body")
        return S3Object(
            content=content,
            content_hash=hashlib.sha256(content).hexdigest(),
            etag=value if isinstance(value := response.get("ETag"), str) else None,
            version_id=value if isinstance(value := response.get("VersionId"), str) else None,
        )

    def read_object(self, uri: str) -> S3Object:
        """Capture one complete object or raise an actionable managed error."""
        SourceDefinition(name="object", type="s3-csv", uri=uri)
        parts = urlsplit(uri)
        try:
            return self._capture(parts.netloc, parts.path.removeprefix("/"))
        except (*S3_TRANSFER_ERRORS, AttributeError, TypeError) as error:
            raise ManagedError(f"Cannot read required S3 CSV source: {uri}") from error

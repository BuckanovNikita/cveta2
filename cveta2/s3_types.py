"""Type definitions for S3 client interfaces."""

from __future__ import annotations

from typing import Any, Protocol


class S3Client(Protocol):
    """Structural protocol for a boto3 S3 client (subset used by cveta2)."""

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        """Retrieve an object from S3."""
        ...

    def list_objects_v2(self, **kwargs: str) -> dict[str, Any]:
        """List objects in a bucket."""
        ...

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        """Upload a local file to S3."""
        ...

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803
        """Put an object to S3."""
        ...

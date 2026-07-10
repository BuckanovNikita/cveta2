"""Reusable dict-backed fake S3 client for tests.

Implements the subset of the boto3 S3 client used by cveta2
(:class:`cveta2.s3_types.S3Client`).  Objects are stored in-memory as
``{"bucket/key": bytes}``.  Missing keys raise a proper
``botocore.exceptions.ClientError`` with the ``NoSuchKey`` code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError


class _FakeBody:
    """Streaming-body stand-in returning fixed bytes."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3Client:
    """In-memory S3 client with call tracking.

    Objects are stored as ``{"bucket/key": bytes}`` by default; with
    ``keyed_by_bucket=False`` bare keys are used (project-storage / sync
    tests).  ``get_calls`` and ``put_calls`` record the store keys in
    call order, so tests can assert whether S3 was touched.
    """

    def __init__(
        self,
        objects: dict[str, bytes] | None = None,
        *,
        keyed_by_bucket: bool = True,
    ) -> None:
        """Seed the store with optional objects (see class docstring)."""
        self.objects: dict[str, bytes] = dict(objects or {})
        self.get_calls: list[str] = []
        self.put_calls: list[str] = []
        self._keyed_by_bucket = keyed_by_bucket

    def _store_key(self, bucket: str, key: str) -> str:
        return f"{bucket}/{key}" if self._keyed_by_bucket else key

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        full_key = self._store_key(Bucket, Key)
        self.get_calls.append(full_key)
        if full_key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": full_key}},
                "GetObject",
            )
        return {"Body": _FakeBody(self.objects[full_key])}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803
        full_key = self._store_key(Bucket, Key)
        self.put_calls.append(full_key)
        self.objects[full_key] = Body

    def list_objects_v2(self, **kwargs: str) -> dict[str, Any]:
        bucket = kwargs.get("Bucket", "")
        prefix = kwargs.get("Prefix", "")
        contents = []
        for full_key, value in self.objects.items():
            key_part = full_key
            if self._keyed_by_bucket:
                bucket_part, _, key_part = full_key.partition("/")
                if bucket_part != bucket or not key_part:
                    continue
            if prefix and not key_part.startswith(prefix):
                continue
            contents.append({"Key": key_part, "Size": len(value)})
        return {"Contents": contents, "IsTruncated": False}

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.objects[self._store_key(bucket, key)] = Path(filename).read_bytes()

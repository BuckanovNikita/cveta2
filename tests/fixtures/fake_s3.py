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
        self.list_requests: list[dict[str, str]] = []
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
        self.list_requests.append(dict(kwargs))
        bucket = kwargs.get("Bucket", "")
        prefix = kwargs.get("Prefix", "")
        delimiter = kwargs.get("Delimiter", "")
        contents = []
        folders: set[str] = set()
        for full_key, value in self.objects.items():
            key_part = full_key
            if self._keyed_by_bucket:
                bucket_part, _, key_part = full_key.partition("/")
                if bucket_part != bucket or not key_part:
                    continue
            if prefix and not key_part.startswith(prefix):
                continue
            # With a delimiter, S3 reports anything nested below one level
            # as a folder rather than as an object.
            remainder = key_part[len(prefix) :]
            if delimiter and delimiter in remainder:
                head = remainder.split(delimiter, 1)[0]
                folders.add(f"{prefix}{head}{delimiter}")
                continue
            contents.append({"Key": key_part, "Size": len(value)})
        response: dict[str, Any] = {"Contents": contents, "IsTruncated": False}
        if folders:
            response["CommonPrefixes"] = [
                {"Prefix": folder} for folder in sorted(folders)
            ]
        return response

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.objects[self._store_key(bucket, key)] = Path(filename).read_bytes()


_LIST_PARAMETERS = frozenset({"Bucket", "Prefix", "ContinuationToken", "Delimiter"})


class PagedFakeS3Client(FakeS3Client):
    """A listing that spans several pages and rejects a malformed request.

    :class:`FakeS3Client` always answers with a single page and tolerates
    whatever it is handed, which leaves the continuation-token branch of
    :func:`cveta2.s3_utils.list_s3_objects` untested.  This one behaves
    like a real bucket instead: it refuses parameters S3 does not know,
    refuses a continuation token other than the one it handed out with
    the previous page, and omits ``Contents`` entirely from an empty page.
    """

    def __init__(
        self,
        pages: list[list[str]],
        *,
        bucket: str = "test-bucket",
    ) -> None:
        """Serve *pages* of object keys, one ``list_objects_v2`` call each."""
        super().__init__(keyed_by_bucket=False)
        self._pages = pages
        self._bucket = bucket
        self._expected_token: str | None = None
        self.list_calls: list[dict[str, str]] = []

    def list_objects_v2(self, **kwargs: str) -> dict[str, Any]:
        self.list_calls.append(dict(kwargs))
        unknown = sorted(set(kwargs) - _LIST_PARAMETERS)
        if unknown:
            msg = f"S3 rejects unknown list_objects_v2 parameters: {unknown}"
            raise TypeError(msg)
        if kwargs.get("Bucket") != self._bucket:
            msg = f"no such bucket: {kwargs.get('Bucket')!r}"
            raise ValueError(msg)
        token = kwargs.get("ContinuationToken")
        if token != self._expected_token:
            msg = f"invalid continuation token: {token!r}"
            raise ValueError(msg)
        return self._page(int(token or 0), kwargs.get("Prefix", ""))

    def _page(self, index: int, prefix: str) -> dict[str, Any]:
        contents = [
            {"Key": key, "Size": len(key)}
            for key in self._pages[index]
            if key.startswith(prefix)
        ]
        response: dict[str, Any] = {"Contents": contents} if contents else {}
        has_more = index + 1 < len(self._pages)
        self._expected_token = str(index + 1) if has_more else None
        if has_more:
            response["IsTruncated"] = True
            response["NextContinuationToken"] = self._expected_token
        return response

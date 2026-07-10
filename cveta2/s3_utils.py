"""Shared S3 utilities used by both image_downloader and image_uploader."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, TypeVar, cast

import boto3
from botocore.config import Config
from botocore.exceptions import ConnectTimeoutError, ReadTimeoutError
from loguru import logger
from tqdm import tqdm

from cveta2._retry import RETRY_ATTEMPTS, network_retry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from cveta2.s3_types import S3Client

_T = TypeVar("_T")

S3_TRANSFER_ERRORS: Final = (OSError, ConnectionError, KeyError)


def run_s3_transfers(
    items: Sequence[_T],
    transfer: Callable[[_T], None],
    describe: Callable[[_T], str],
    *,
    desc: str,
    unit: str,
) -> tuple[int, int]:
    """Run *transfer* per item under a tqdm bar; return ``(ok, failed)``.

    Each failure is logged with ``logger.exception``; callers log the
    summary line after the loop.
    """
    ok = failed = 0
    for item in tqdm(items, desc=desc, unit=unit, leave=False):
        try:
            transfer(item)
            ok += 1
        except S3_TRANSFER_ERRORS:
            logger.exception(f"Не удалось загрузить {describe(item)}")
            failed += 1
    return ok, failed


def names_with_basename_fallback(pairs: Iterable[tuple[str, _T]]) -> dict[str, _T]:
    """Map each name to its value, also keyed by basename (first wins).

    Basename fallback handles subfolder frame names
    (e.g. ``"2026-02/img.jpg"`` is also accessible via ``"img.jpg"``).
    """
    result: dict[str, _T] = {}
    for name, value in pairs:
        result[name] = value
        base = PurePosixPath(name).name
        if base not in result:
            result[base] = value
    return result


s3_retry = network_retry(
    (OSError, ConnectionError, ConnectTimeoutError, ReadTimeoutError), label="S3"
)

_S3_CONNECT_TIMEOUT = 10.0


class _DataTimeoutDefault:
    """Process-wide default read timeout (seconds) for S3 clients."""

    value: float | None = None


def set_default_data_timeout(timeout: float | None) -> None:
    """Set the default S3 read timeout used by :func:`make_s3_client`.

    ``None`` or ``0`` disables the timeout (boto3 defaults apply).
    """
    _DataTimeoutDefault.value = timeout


def make_s3_client(endpoint_url: str | None = None) -> S3Client:
    """Create a boto3 S3 client honoring the default data timeout."""
    session = boto3.Session()
    if _DataTimeoutDefault.value:
        timeout_config = Config(
            connect_timeout=_S3_CONNECT_TIMEOUT,
            read_timeout=_DataTimeoutDefault.value,
            retries={"max_attempts": RETRY_ATTEMPTS, "mode": "standard"},
        )
        return cast(
            "S3Client",
            session.client("s3", endpoint_url=endpoint_url, config=timeout_config),
        )
    return cast("S3Client", session.client("s3", endpoint_url=endpoint_url))


@s3_retry
def s3_get_bytes(s3_client: S3Client, bucket: str, key: str) -> bytes:
    """Download an S3 object body as bytes."""
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    data: bytes = resp["Body"].read()
    return data


def parse_sync_root(root: str) -> tuple[str | None, str]:
    """Parse a sync root string into ``(bucket, prefix)``.

    ``s3://bucket/some/prefix`` -> ``("bucket", "some/prefix")``,
    ``s3://bucket`` -> ``("bucket", "")``, a bare ``some/prefix`` ->
    ``(None, "some/prefix")``.  Trailing slashes are stripped.

    Raises
    ------
    ValueError
        When *root* is empty or an ``s3://`` URL has no bucket name.

    """
    cleaned = root.strip()
    if cleaned.startswith("s3://"):
        bucket, _, prefix = cleaned.removeprefix("s3://").partition("/")
        if not bucket:
            msg = f"Некорректный sync root {root!r}: отсутствует имя бакета."
            raise ValueError(msg)
        return (bucket, prefix.rstrip("/"))
    prefix = cleaned.rstrip("/")
    if not prefix:
        msg = f"Некорректный sync root {root!r}: пустое значение."
        raise ValueError(msg)
    return (None, prefix)


def build_s3_key(prefix: str, frame_name: str) -> str:
    """Construct the S3 object key for a frame.

    If *frame_name* already starts with *prefix*, it is used as-is.
    Otherwise *prefix/frame_name* is returned (or just *frame_name*
    when *prefix* is empty).
    """
    if not prefix:
        return frame_name
    if frame_name.startswith(prefix):
        return frame_name
    return f"{prefix}/{frame_name}"


def strip_key_prefix(key: str, prefix: str) -> str:
    """Return *key* with a leading *prefix* removed, keeping subfolders.

    When *key* does not start with *prefix* (or *prefix* is empty), the
    key is returned unchanged.
    """
    if prefix and key.startswith(prefix):
        return key[len(prefix) :].lstrip("/")
    return key


def list_s3_objects(
    s3_client: S3Client,
    bucket: str,
    prefix: str,
) -> list[tuple[str, str]]:
    """List all S3 objects under *prefix* and return ``(key, local_name)`` pairs.

    The *local_name* is the object key with the prefix stripped, suitable
    for saving as a flat file name.  Empty names (the prefix directory
    marker itself) are skipped.
    """
    objects: list[tuple[str, str]] = []
    kwargs: dict[str, str] = {"Bucket": bucket}
    if prefix:
        kwargs["Prefix"] = prefix
    while True:
        resp = s3_client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            key: str = obj["Key"]
            name = strip_key_prefix(key, prefix)
            if name:
                objects.append((key, name))
        if not resp.get("IsTruncated"):
            break
        kwargs["ContinuationToken"] = resp["NextContinuationToken"]
    return objects

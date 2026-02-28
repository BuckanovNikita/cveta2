"""Shared S3 utilities used by both image_downloader and image_uploader."""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.s3_types import S3Client

s3_retry = retry(
    retry=retry_if_exception_type((OSError, ConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


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
            name = key[len(prefix) :].lstrip("/") if prefix else key
            if name:
                objects.append((key, name))
        if not resp.get("IsTruncated"):
            break
        kwargs["ContinuationToken"] = resp["NextContinuationToken"]
    return objects


def make_s3_client(cs_info: CloudStorageInfo) -> S3Client:
    """Create a boto3 S3 client from cloud storage info."""
    client: S3Client = boto3.Session().client(
        "s3",
        endpoint_url=cs_info.endpoint_url or None,
    )
    return client

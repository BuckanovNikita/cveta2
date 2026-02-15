"""Upload images to S3 cloud storage for CVAT task creation.

Reuses :class:`CloudStorageInfo`, :func:`_build_s3_key`,
:func:`_list_s3_objects` and the S3 retry decorator from
:mod:`cveta2.image_downloader`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import boto3
from loguru import logger
from pydantic import BaseModel
from tqdm import tqdm

from cveta2.image_downloader import (
    CloudStorageInfo,
    _build_s3_key,
    _list_s3_objects,
    _s3_retry,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Upload stats
# ---------------------------------------------------------------------------


class UploadStats(BaseModel):
    """Result counters for an image upload run."""

    uploaded: int = 0
    skipped_existing: int = 0
    failed: int = 0
    total: int = 0


# ---------------------------------------------------------------------------
# Image resolution
# ---------------------------------------------------------------------------


def resolve_images(
    image_names: set[str],
    search_dirs: list[Path],
) -> tuple[dict[str, Path], list[str]]:
    """Find image files on disk by searching *search_dirs* in order.

    Returns
    -------
    found : dict[str, Path]
        Mapping ``image_name -> local_path`` for images that were found.
    missing : list[str]
        Image names that could not be located in any search directory.

    """
    found: dict[str, Path] = {}
    remaining = set(image_names)

    for search_dir in search_dirs:
        if not search_dir.is_dir():
            logger.debug(f"Директория поиска не существует: {search_dir}")
            continue
        for name in list(remaining):
            candidate = search_dir / name
            if candidate.is_file():
                found[name] = candidate
                remaining.discard(name)
        if not remaining:
            break

    missing = sorted(remaining)
    return found, missing


# ---------------------------------------------------------------------------
# S3 uploader
# ---------------------------------------------------------------------------


@_s3_retry
def _upload_one_s3(
    s3_client: Any,  # noqa: ANN401
    bucket: str,
    key: str,
    local_path: Path,
) -> None:
    """Upload a single local file to S3."""
    s3_client.upload_file(str(local_path), bucket, key)


class S3Uploader:
    """Upload images to S3 cloud storage, skipping already-existing files.

    Uses the same S3 key construction as :class:`ImageDownloader` (via
    :func:`_build_s3_key`) to ensure consistency between upload and
    download paths.
    """

    def upload(
        self,
        cs_info: CloudStorageInfo,
        images: dict[str, Path],
    ) -> UploadStats:
        """Upload *images* to S3 under *cs_info* prefix.

        Parameters
        ----------
        cs_info:
            Cloud storage metadata (bucket, prefix, endpoint).
        images:
            Mapping ``image_name -> local_path`` of files to upload.

        Returns
        -------
        UploadStats
            Counters of uploaded / skipped / failed files.

        """
        if not images:
            return UploadStats(total=0)

        stats = UploadStats(total=len(images))

        s3 = boto3.Session().client(
            "s3",
            endpoint_url=cs_info.endpoint_url or None,
        )

        # List existing objects to skip re-uploads
        existing_keys = self._list_existing_keys(s3, cs_info)

        to_upload: list[tuple[str, str, Path]] = []  # (name, key, path)
        for name, local_path in images.items():
            s3_key = _build_s3_key(cs_info.prefix, name)
            if s3_key in existing_keys:
                stats.skipped_existing += 1
            else:
                to_upload.append((name, s3_key, local_path))

        if not to_upload:
            logger.info(
                f"Все {stats.skipped_existing} изображений уже загружены "
                f"в s3://{cs_info.bucket}/{cs_info.prefix}"
            )
            return stats

        for name, s3_key, local_path in tqdm(
            to_upload, desc="Uploading to S3", unit="file", leave=False
        ):
            try:
                _upload_one_s3(s3, cs_info.bucket, s3_key, local_path)
                stats.uploaded += 1
            except (OSError, ConnectionError):
                logger.exception(f"Не удалось загрузить {name} (key={s3_key})")
                stats.failed += 1

        logger.info(
            f"S3 upload: {stats.uploaded} загружено, "
            f"{stats.skipped_existing} уже на S3, {stats.failed} ошибок "
            f"(всего {stats.total})"
        )
        return stats

    @staticmethod
    def _list_existing_keys(
        s3_client: Any,  # noqa: ANN401
        cs_info: CloudStorageInfo,
    ) -> set[str]:
        """Return the set of existing S3 keys under the cloud storage prefix."""
        objects = _list_s3_objects(s3_client, cs_info.bucket, cs_info.prefix)
        return {key for key, _name in objects}

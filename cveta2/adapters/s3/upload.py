"""Upload images to S3 cloud storage for CVAT task creation.

Reuses :class:`CloudStorageInfo` from :mod:`cveta2.adapters.s3.download`
and S3 utilities from :mod:`cveta2.adapters.s3.utils`.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from loguru import logger

from cveta2.adapters.s3.types import S3Client, Transfer
from cveta2.adapters.s3.utils import (
    list_s3_objects,
    make_s3_client,
    run_s3_transfers,
    s3_retry,
)
from cveta2.domain.paths import build_s3_key, pick_latest_duplicate
from cveta2.domain.storage import CloudStorageInfo, UploadStats

_S3_DUPLICATE_CONTEXT = "S3"
_UPLOAD_DESC = "Uploading to S3"
_UPLOAD_UNIT = "file"


def build_server_file_mapping(
    cs_info: CloudStorageInfo,
    image_names: Iterable[str],
    s3_client: S3Client | None = None,
    pinned: dict[str, str] | None = None,
) -> tuple[dict[str, str], set[str]]:
    """Map image names to their S3 ``server_file`` paths relative to prefix.

    For each *image_name*:

    * If a matching file already exists on S3, its relative path is reused
      (e.g. ``"img.jpg"`` or ``"2026-01/img.jpg"``).
    * If the image is new, it is assigned to a month-based subfolder
      using the current UTC month (``"YYYY-MM/img.jpg"``).

    When the same basename appears under multiple S3 paths the **latest**
    (lexicographic max — i.e. most recent month folder) wins and a warning
    is logged.

    *pinned* replaces the computed mapping with one an earlier run already
    decided, while still listing the bucket for *existing_keys*.  A resumed
    upload must reuse the earlier assignment: :func:`_assign_month_folder`
    reads the clock, so a run resumed in a new month would otherwise place
    its remaining images somewhere the frame order does not expect.

    Returns
    -------
    name_to_server_file : dict[str, str]
        Mapping ``image_name → server_file`` (path relative to prefix).
    existing_keys : set[str]
        Full S3 keys of objects that already exist under *cs_info.prefix*;
        :meth:`S3Uploader.upload` skips every image whose key is among them.

    """
    client = s3_client or make_s3_client(cs_info.endpoint_url or None)
    objects = list_s3_objects(client, cs_info.bucket, cs_info.prefix)
    existing_keys: set[str] = {key for key, _name in objects}
    if pinned is not None:
        return dict(pinned), existing_keys

    resolved = _resolve_duplicate_basenames(name for _key, name in objects)
    name_to_server_file = {
        image_name: resolved.get(image_name) or _assign_month_folder(image_name)
        for image_name in image_names
    }
    return name_to_server_file, existing_keys


def _resolve_duplicate_basenames(names: Iterable[str]) -> dict[str, str]:
    """Map each basename to its relative S3 name, latest month folder winning."""
    basename_to_names: dict[str, list[str]] = {}
    for name in names:
        basename_to_names.setdefault(PurePosixPath(name).name, []).append(name)
    return {
        base: pick_latest_duplicate(_S3_DUPLICATE_CONTEXT, base, candidates)
        for base, candidates in basename_to_names.items()
    }


def _assign_month_folder(image_name: str) -> str:
    """Place a new image into the current UTC month folder (``YYYY-MM/name``)."""
    month_prefix = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    return f"{month_prefix}/{image_name}"


@s3_retry
def _upload_one_s3(s3: S3Client, local_path: Path, bucket: str, key: str) -> None:
    """Upload a single local file to S3."""
    s3.upload_file(str(local_path), bucket, key)


class S3Uploader:
    """Upload images to S3 cloud storage, skipping already-existing files.

    Uses the same S3 key construction as :class:`ImageDownloader` (via
    :func:`build_s3_key`) to ensure consistency between upload and
    download paths.
    """

    def upload(
        self,
        cs_info: CloudStorageInfo,
        images: dict[str, Path],
        name_to_server_file: dict[str, str],
        existing_keys: set[str],
    ) -> UploadStats:
        """Upload *images* to S3 under *cs_info* prefix.

        Parameters
        ----------
        cs_info:
            Cloud storage metadata (bucket, prefix, endpoint).
        images:
            Mapping ``image_name -> local_path`` of files to upload.
        name_to_server_file:
            Mapping ``image_name -> server_file`` (path relative to prefix)
            covering every name in *images*; the server_file builds the S3
            key.  Produced by :func:`build_server_file_mapping`.
        existing_keys:
            Full S3 keys already present under the prefix, as returned by
            :func:`build_server_file_mapping`; images whose key is among
            them are skipped.

        Returns
        -------
        UploadStats
            Counters of uploaded / skipped / failed files.

        """
        if not images:
            return UploadStats(total=0)

        stats = UploadStats(total=len(images))

        s3 = make_s3_client(cs_info.endpoint_url or None)

        to_upload: list[Transfer] = []
        for name, local_path in images.items():
            s3_key = build_s3_key(cs_info.prefix, name_to_server_file[name])
            if s3_key in existing_keys:
                stats.skipped_existing += 1
            else:
                to_upload.append(Transfer(name=name, key=s3_key, path=local_path))

        if not to_upload:
            logger.info(
                f"Все {stats.skipped_existing} изображений уже загружены "
                f"в s3://{cs_info.bucket}/{cs_info.prefix}"
            )
            return stats

        stats.uploaded, stats.failed = run_s3_transfers(
            to_upload,
            lambda t: _upload_one_s3(s3, t.path, cs_info.bucket, t.key),
            lambda t: f"{t.name} (key={t.key})",
            desc=_UPLOAD_DESC,
            unit=_UPLOAD_UNIT,
        )

        logger.info(
            f"S3 upload: {stats.uploaded} загружено, "
            f"{stats.skipped_existing} уже на S3, {stats.failed} ошибок "
            f"(всего {stats.total})"
        )
        return stats


class S3UploadStorage(S3Uploader):
    """Outgoing image-storage adapter for application upload workflows."""

    mapping = staticmethod(build_server_file_mapping)

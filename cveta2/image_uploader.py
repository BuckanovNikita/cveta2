"""Upload images to S3 cloud storage for CVAT task creation.

Reuses :class:`CloudStorageInfo` from :mod:`cveta2.image_downloader`
and S3 utilities from :mod:`cveta2.s3_utils`.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel

from cveta2.s3_utils import (
    build_s3_key,
    list_s3_objects,
    make_s3_client,
    run_s3_transfers,
    s3_retry,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.s3_types import S3Client


class UploadStats(BaseModel):
    """Result counters for an image upload run."""

    uploaded: int = 0
    skipped_existing: int = 0
    failed: int = 0
    total: int = 0


def _build_basename_index(search_dir: Path) -> dict[str, list[Path]]:
    """Walk *search_dir* recursively, mapping basename → sorted file paths."""
    index: dict[str, list[Path]] = {}
    for root, _dirs, files in os.walk(search_dir):
        root_path = Path(root)
        for file_name in files:
            index.setdefault(file_name, []).append(root_path / file_name)
    for paths in index.values():
        paths.sort()
    return index


def _match_recursive(
    search_dir: Path,
    name: str,
    index: dict[str, list[Path]],
) -> Path | None:
    """Match *name* by basename in the recursive *index* of *search_dir*.

    When the same basename exists at several paths the lexicographic max
    wins (mirrors the "latest month folder" convention of
    :func:`build_server_file_mapping`).
    """
    candidates = index.get(PurePosixPath(name).name)
    if not candidates:
        return None
    if len(candidates) > 1:
        logger.warning(
            f"Дубликаты в {search_dir} для {name!r}: "
            f"{[str(c) for c in candidates]} — используем {str(candidates[-1])!r}"
        )
    return candidates[-1]


def resolve_images(
    image_names: Iterable[str],
    search_dirs: list[Path],
) -> tuple[dict[str, Path], list[str]]:
    """Find image files on disk by searching *search_dirs* in order.

    Each directory is probed in two passes: a direct path join (supports
    names containing subpaths), then a recursive basename search over the
    whole tree.  Earlier search directories always win over later ones.

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
        if not remaining:
            break
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
        index = _build_basename_index(search_dir)
        for name in list(remaining):
            match = _match_recursive(search_dir, name, index)
            if match is not None:
                found[name] = match
                remaining.discard(name)

    missing = sorted(remaining)
    return found, missing


def build_server_file_mapping(
    cs_info: CloudStorageInfo,
    image_names: Iterable[str],
    s3_client: S3Client | None = None,
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

    Returns
    -------
    name_to_server_file : dict[str, str]
        Mapping ``image_name → server_file`` (path relative to prefix).
    existing_keys : set[str]
        Full S3 keys of objects that already exist under *cs_info.prefix*.
        Passed to :meth:`S3Uploader.upload` to avoid a redundant listing.

    """
    client = s3_client or make_s3_client(cs_info.endpoint_url or None)
    objects = list_s3_objects(client, cs_info.bucket, cs_info.prefix)
    existing_keys: set[str] = {key for key, _name in objects}

    # Build basename → relative-name lookup.
    # If multiple objects share the same basename, keep the lexicographic max
    # (latest month folder).
    basename_to_name: dict[str, list[str]] = {}
    for _key, name in objects:
        base = PurePosixPath(name).name
        basename_to_name.setdefault(base, []).append(name)

    resolved: dict[str, str] = {}
    for base, names in basename_to_name.items():
        if len(names) > 1:
            names_sorted = sorted(names)
            logger.warning(
                f"Дубликат на S3 для {base!r}: {names_sorted} — "
                f"используем {names_sorted[-1]!r}"
            )
            resolved[base] = names_sorted[-1]
        else:
            resolved[base] = names[0]

    month_prefix = datetime.now(tz=timezone.utc).strftime("%Y-%m")

    name_to_server_file: dict[str, str] = {}
    for image_name in image_names:
        if image_name in resolved:
            name_to_server_file[image_name] = resolved[image_name]
        else:
            name_to_server_file[image_name] = f"{month_prefix}/{image_name}"

    return name_to_server_file, existing_keys


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
        name_to_server_file: dict[str, str] | None = None,
        existing_keys: set[str] | None = None,
    ) -> UploadStats:
        """Upload *images* to S3 under *cs_info* prefix.

        Parameters
        ----------
        cs_info:
            Cloud storage metadata (bucket, prefix, endpoint).
        images:
            Mapping ``image_name -> local_path`` of files to upload.
        name_to_server_file:
            Optional mapping ``image_name -> server_file`` (path relative
            to prefix).  When provided, the server_file is used to build
            the S3 key instead of the bare image name.  Produced by
            :func:`build_server_file_mapping`.
        existing_keys:
            Pre-computed set of existing S3 keys.  When provided, the
            internal ``list_s3_objects`` call is skipped.

        Returns
        -------
        UploadStats
            Counters of uploaded / skipped / failed files.

        """
        if not images:
            return UploadStats(total=0)

        stats = UploadStats(total=len(images))

        s3 = make_s3_client(cs_info.endpoint_url or None)

        # List existing objects to skip re-uploads
        if existing_keys is None:
            objects = list_s3_objects(s3, cs_info.bucket, cs_info.prefix)
            existing_keys = {key for key, _name in objects}

        to_upload: list[tuple[str, str, Path]] = []  # (name, key, path)
        for name, local_path in images.items():
            server_file = (
                name_to_server_file[name]
                if name_to_server_file and name in name_to_server_file
                else name
            )
            s3_key = build_s3_key(cs_info.prefix, server_file)
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

        stats.uploaded, stats.failed = run_s3_transfers(
            to_upload,
            lambda item: _upload_one_s3(s3, item[2], cs_info.bucket, item[1]),
            lambda item: f"{item[0]} (key={item[1]})",
            desc="Uploading to S3",
            unit="file",
        )

        logger.info(
            f"S3 upload: {stats.uploaded} загружено, "
            f"{stats.skipped_existing} уже на S3, {stats.failed} ошибок "
            f"(всего {stats.total})"
        )
        return stats

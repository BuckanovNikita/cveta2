"""Download project images from S3 cloud storage attached to CVAT.

When *project_cloud_storage* is provided, all images (including images without
annotations) are downloaded from that storage by name lookup; task
``source_storage`` is not used. When *project_cloud_storage* is None, all
pending images are counted as failed. Already-cached files are skipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from loguru import logger
from pydantic import BaseModel
from tqdm import tqdm

from cveta2.s3_utils import (
    build_s3_key,
    list_s3_objects,
    make_s3_client,
    names_with_basename_fallback,
    s3_get_bytes,
    strip_key_prefix,
)

if TYPE_CHECKING:
    from cveta2.models import ProjectAnnotations
    from cveta2.s3_types import S3Client


class CloudStorageInfo(BaseModel):
    """Parsed cloud storage metadata from CVAT."""

    id: int
    bucket: str
    prefix: str
    endpoint_url: str


def parse_cloud_storage(cs_raw: object) -> CloudStorageInfo:
    """Extract bucket, prefix, endpoint from a CVAT cloud storage SDK object.

    Uses ``getattr`` because the CVAT SDK cloud storage object is opaque
    and its attributes vary across SDK versions.  This is an intentional
    exception to the project style rule "avoid getattr" (see CLAUDE.md).

    Mirrors the logic in ``scripts/clone_project_to_s3.py``.
    """
    specific = str(getattr(cs_raw, "specific_attributes", None) or "")
    parsed = parse_qs(specific)
    prefix = (parsed.get("prefix") or [""])[0]
    endpoint_url = (parsed.get("endpoint_url") or [""])[0]
    return CloudStorageInfo(
        id=int(getattr(cs_raw, "id", 0)),
        bucket=str(getattr(cs_raw, "resource", "")),
        prefix=prefix,
        endpoint_url=endpoint_url,
    )


class DownloadStats(BaseModel):
    """Result counters for an image download run."""

    downloaded: int = 0
    cached: int = 0
    failed: int = 0
    total: int = 0


class ImageDownloader:
    """Download project images from S3 into a user-specified directory.

    By default images are saved flat as ``target_dir / image_name``.
    With *ignored_prefix* set (the ``cache.projects.<name>.ignored_prefix``
    setting), the local layout mirrors the S3 key below that prefix, so
    subfolders are preserved.
    """

    def __init__(self, target_dir: Path, ignored_prefix: str | None = None) -> None:
        """Store the target directory and optional S3 prefix to strip."""
        self._target_dir = target_dir
        self._ignored_prefix = ignored_prefix

    def download(
        self,
        annotations: ProjectAnnotations,
        project_cloud_storage: CloudStorageInfo | None = None,
    ) -> DownloadStats:
        """Download images referenced in *annotations*.

        Returns counters of downloaded / cached / failed images.
        When *project_cloud_storage* is provided, all images are downloaded
        from that storage by name; task source_storage is not used. When
        *project_cloud_storage* is None, all pending images are counted
        as failed.
        """
        image_tasks = self._collect_unique_images(annotations)
        if not image_tasks:
            return DownloadStats(total=0)

        stats = DownloadStats(total=len(image_tasks))
        pending = self._filter_cached(image_tasks, stats, project_cloud_storage)
        if not pending:
            logger.info(
                f"Все {stats.cached} изображений уже загружены в {self._target_dir}"
            )
            return stats

        self._target_dir.mkdir(parents=True, exist_ok=True)
        self._download_all(pending, stats, project_cloud_storage)

        logger.info(
            f"Загрузка изображений: {stats.downloaded} новых, "
            f"{stats.cached} из кэша, {stats.failed} ошибок "
            f"(всего {stats.total})"
        )
        return stats

    @staticmethod
    def _collect_unique_images(
        annotations: ProjectAnnotations,
    ) -> dict[str, str]:
        """Return ``{image_name: frame_ref}`` for unique images.

        *frame_ref* is the original (possibly nested) CVAT frame name
        used for S3 key lookup; first occurrence wins.  Deleted images
        are not included (they live in ``deleted_images``, not
        ``annotations``).
        """
        result: dict[str, str] = {}
        for record in annotations.annotations:
            if record.image_name not in result:
                result[record.image_name] = record.frame_path or record.image_name
        return result

    def _dest_path(
        self,
        image_name: str,
        frame_ref: str,
        project_cloud_storage: CloudStorageInfo | None,
    ) -> Path:
        """Local destination: flat by default, nested with ``ignored_prefix``."""
        if self._ignored_prefix and project_cloud_storage is not None:
            full_key = build_s3_key(project_cloud_storage.prefix, frame_ref)
            return self._target_dir / strip_key_prefix(full_key, self._ignored_prefix)
        return self._target_dir / image_name

    def _filter_cached(
        self,
        image_tasks: dict[str, str],
        stats: DownloadStats,
        project_cloud_storage: CloudStorageInfo | None,
    ) -> dict[str, str]:
        """Remove already-cached images, updating *stats*. Return pending."""
        pending: dict[str, str] = {}
        for image_name, frame_ref in image_tasks.items():
            if self._dest_path(image_name, frame_ref, project_cloud_storage).exists():
                stats.cached += 1
            else:
                pending[image_name] = frame_ref
        return pending

    def _download_all(
        self,
        pending: dict[str, str],
        stats: DownloadStats,
        project_cloud_storage: CloudStorageInfo | None = None,
    ) -> None:
        """Download all pending images from project cloud storage by name lookup."""
        if project_cloud_storage is None:
            stats.failed += len(pending)
            if pending:
                logger.warning(
                    "Project cloud storage не задан — все изображения помечены "
                    "как failed. Укажите project_id при вызове download_images."
                )
            return
        s3_client = make_s3_client(project_cloud_storage.endpoint_url or None)
        name_to_key = self._build_project_storage_name_map(
            s3_client,
            project_cloud_storage.bucket,
            project_cloud_storage.prefix,
        )
        for image_name, frame_ref in tqdm(
            pending.items(),
            desc="Downloading from project storage",
            unit="img",
            leave=False,
        ):
            s3_key: str | None = (
                name_to_key.get(frame_ref)
                or name_to_key.get(image_name)
                or name_to_key.get(Path(image_name).name)
            )
            if s3_key is None:
                stats.failed += 1
                continue
            dest = self._dest_path(image_name, frame_ref, project_cloud_storage)
            try:
                _download_one_s3(
                    s3_client,
                    project_cloud_storage.bucket,
                    s3_key,
                    dest,
                )
                stats.downloaded += 1
            except (OSError, ConnectionError, KeyError):
                logger.exception(f"Не удалось загрузить {image_name} (key={s3_key})")
                stats.failed += 1

    @staticmethod
    def _build_project_storage_name_map(
        s3_client: S3Client,
        bucket: str,
        prefix: str,
    ) -> dict[str, str]:
        """List objects under prefix; return name -> S3 key (full name + basename)."""
        pairs = list_s3_objects(s3_client, bucket, prefix)
        return names_with_basename_fallback((name, key) for key, name in pairs)


def _download_one_s3(
    s3_client: S3Client,
    bucket: str,
    key: str,
    dest: Path,
) -> None:
    """Download a single S3 object to *dest*."""
    data = s3_get_bytes(s3_client, bucket, key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


class S3Syncer:
    """Sync all objects under an S3 cloud storage prefix to a local directory.

    Unlike :class:`ImageDownloader` which downloads only images referenced
    in annotations, this class lists **all** objects in the S3 prefix and
    downloads any that are missing locally.  It never deletes local files
    and never uploads to S3.  With *ignored_prefix* set, local names are
    the S3 keys below that prefix instead of below the storage prefix.
    """

    def __init__(self, target_dir: Path, ignored_prefix: str | None = None) -> None:
        """Store the target directory and optional S3 prefix to strip."""
        self._target_dir = target_dir
        self._ignored_prefix = ignored_prefix

    def sync(self, cs_info: CloudStorageInfo) -> DownloadStats:
        """List all objects under *cs_info* prefix and download missing ones.

        Returns counters of downloaded / cached / failed files.
        """
        s3 = make_s3_client(cs_info.endpoint_url or None)
        objects = list_s3_objects(s3, cs_info.bucket, cs_info.prefix)
        if self._ignored_prefix:
            objects = [
                (key, strip_key_prefix(key, self._ignored_prefix)) for key, _ in objects
            ]
        if not objects:
            logger.info(f"Нет объектов в s3://{cs_info.bucket}/{cs_info.prefix}")
            return DownloadStats(total=0)

        stats = DownloadStats(total=len(objects))
        to_download: list[tuple[str, str]] = []
        for key, name in objects:
            dest = self._target_dir / name
            if dest.exists():
                stats.cached += 1
            else:
                to_download.append((key, name))

        if not to_download:
            logger.info(f"Все {stats.cached} файлов уже загружены в {self._target_dir}")
            return stats

        self._target_dir.mkdir(parents=True, exist_ok=True)
        for key, name in tqdm(
            to_download, desc="Syncing from S3", unit="file", leave=False
        ):
            dest = self._target_dir / name
            try:
                _download_one_s3(s3, cs_info.bucket, key, dest)
                stats.downloaded += 1
            except (OSError, ConnectionError, KeyError):
                logger.exception(f"Не удалось загрузить {name} (key={key})")
                stats.failed += 1

        logger.info(
            f"S3 sync: {stats.downloaded} загружено, "
            f"{stats.cached} из кэша, {stats.failed} ошибок "
            f"(всего {stats.total})"
        )
        return stats

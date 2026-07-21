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

from cveta2.fs_utils import ensure_shared_dir, write_shared_bytes
from cveta2.s3_types import Transfer
from cveta2.s3_utils import (
    build_s3_key,
    list_s3_objects,
    make_s3_client,
    names_with_basename_fallback,
    run_s3_transfers,
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


def _download_pending(  # noqa: PLR0913
    s3_client: S3Client,
    bucket: str,
    pending: list[Transfer],
    stats: DownloadStats,
    *,
    desc: str,
    unit: str,
) -> None:
    """Download *pending* transfers, adding the outcome counts to *stats*."""
    ok, failed = run_s3_transfers(
        pending,
        lambda t: _download_one_s3(s3_client, bucket, t.key, t.path),
        lambda t: f"{t.name} (key={t.key})",
        desc=desc,
        unit=unit,
    )
    stats.downloaded += ok
    stats.failed += failed


def _log_download_summary(what: str, stats: DownloadStats) -> None:
    """Log the downloaded / cached / failed / total counters."""
    logger.info(
        f"{what}: {stats.downloaded} загружено, "
        f"{stats.cached} из кэша, {stats.failed} ошибок "
        f"(всего {stats.total})"
    )


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

        ensure_shared_dir(self._target_dir)
        self._download_all(pending, stats, project_cloud_storage)

        _log_download_summary("Загрузка изображений", stats)
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
        frame_ref: str,
        project_cloud_storage: CloudStorageInfo | None,
    ) -> Path:
        """Local destination mirroring the S3 layout below the storage prefix.

        With ``ignored_prefix`` set, only that leading key part is
        stripped instead of the full storage prefix (keeping more of the
        S3 hierarchy locally).
        """
        if self._ignored_prefix and project_cloud_storage is not None:
            full_key = build_s3_key(project_cloud_storage.prefix, frame_ref)
            return self._target_dir / strip_key_prefix(full_key, self._ignored_prefix)
        return self._target_dir / frame_ref

    def _filter_cached(
        self,
        image_tasks: dict[str, str],
        stats: DownloadStats,
        project_cloud_storage: CloudStorageInfo | None,
    ) -> dict[str, str]:
        """Remove already-cached images, updating *stats*. Return pending."""
        pending: dict[str, str] = {}
        for image_name, frame_ref in image_tasks.items():
            if self._dest_path(frame_ref, project_cloud_storage).exists():
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
        to_download: list[Transfer] = []
        missing: list[str] = []
        for image_name, frame_ref in pending.items():
            s3_key: str | None = (
                name_to_key.get(frame_ref)
                or name_to_key.get(image_name)
                or name_to_key.get(Path(image_name).name)
            )
            if s3_key is None:
                missing.append(image_name)
                continue
            dest = self._dest_path(frame_ref, project_cloud_storage)
            to_download.append(Transfer(name=image_name, key=s3_key, path=dest))
        if missing:
            stats.failed += len(missing)
            logger.warning(
                f"Не найдены на S3 ({len(missing)} шт.): "
                f"{', '.join(missing[:10])}"
                f"{'...' if len(missing) > 10 else ''}"
            )
        _download_pending(
            s3_client,
            project_cloud_storage.bucket,
            to_download,
            stats,
            desc="Downloading from project storage",
            unit="img",
        )

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
    ensure_shared_dir(dest.parent)
    write_shared_bytes(dest, data)


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
        to_download = [
            Transfer(name=name, key=key, path=self._target_dir / name)
            for key, name in objects
            if not (self._target_dir / name).exists()
        ]
        stats.cached = stats.total - len(to_download)

        if not to_download:
            logger.info(f"Все {stats.cached} файлов уже загружены в {self._target_dir}")
            return stats

        ensure_shared_dir(self._target_dir)
        _download_pending(
            s3,
            cs_info.bucket,
            to_download,
            stats,
            desc="Syncing from S3",
            unit="file",
        )

        _log_download_summary("S3 sync", stats)
        return stats

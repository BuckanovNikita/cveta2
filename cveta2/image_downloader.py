"""Download project images from S3 cloud storage attached to CVAT.

When *project_cloud_storage* is provided, all images (including images without
annotations) are downloaded from that storage by name lookup; task
``source_storage`` is not used. When *project_cloud_storage* is None, all
pending images are counted as failed. Already-cached files are skipped.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import parse_qs

from loguru import logger
from pydantic import BaseModel

from cveta2._concurrency import Workers, run_concurrent
from cveta2.exceptions import Cveta2Error
from cveta2.fs_utils import ensure_shared_dir, replace_shared_bytes
from cveta2.s3_types import Transfer
from cveta2.s3_utils import (
    build_s3_key,
    list_s3_objects,
    make_s3_client,
    names_with_basename_fallback,
    run_s3_transfers,
    s3_get_bytes,
    s3_object_exists,
    strip_key_prefix,
)

if TYPE_CHECKING:
    from pathlib import Path

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

    def summary(self) -> str:
        """Render the counters as the one-line log summary shared by every run."""
        return (
            f"{self.downloaded} загружено, {self.cached} из кэша, "
            f"{self.failed} ошибок (всего {self.total})"
        )


class _ProgressLabels(NamedTuple):
    """Caption and unit noun of one transfer batch's progress bar."""

    desc: str
    unit: str


_PROJECT_STORAGE_PROGRESS = _ProgressLabels("Downloading from project storage", "img")
_S3_SYNC_PROGRESS = _ProgressLabels("Syncing from S3", "file")

_MISSING_PREVIEW_LIMIT = 10
"""How many not-found image names the warning lists before collapsing the rest."""

_DIRECT_KEY_PROBE_LIMIT = 2000
"""Above this many pending images, list the prefix instead of probing keys.

Probing costs one HEAD per image; listing costs one round-trip per thousand
keys under the whole project prefix — every task's images, not just the
fetched one's.  Probing therefore wins by orders of magnitude when a fetch
wants a few images out of a large project, and loses when it wants nearly
all of them, which is what a whole-project fetch does.
"""


def _validate_relative_key(value: str, *, original: str) -> str:
    """Return a safe relative POSIX key, rejecting filesystem traversal."""
    parts = value.split("/")
    if not value or any(part in {"", ".", ".."} for part in parts):
        raise Cveta2Error(
            f"Небезопасный путь изображения {original!r}: "
            f"путь должен оставаться внутри настроенного корня хранилища"
        )
    return PurePosixPath(*parts).as_posix()


def _canonical_frame_key(prefix: str, frame_ref: str) -> str:
    """Resolve a relative or rooted frame reference within an S3 prefix."""
    if PurePosixPath(frame_ref).is_absolute():
        unrooted = frame_ref.lstrip("/")
        if prefix:
            prefix_dir = f"{prefix.rstrip('/')}/"
            if unrooted != prefix.rstrip("/") and not unrooted.startswith(prefix_dir):
                raise Cveta2Error(
                    f"Абсолютный путь изображения {frame_ref!r} находится вне "
                    f"настроенного корня {prefix!r}"
                )
        key = unrooted
    else:
        key = build_s3_key(prefix, frame_ref)
    return _validate_relative_key(key, original=frame_ref)


def _local_name_from_key(key: str, root: str, *, original: str) -> str:
    """Turn a canonical S3 key into a safe path below the local cache root."""
    relative = strip_key_prefix(key, root).lstrip("/")
    return _validate_relative_key(relative, original=original)


def _confined_destination(target_dir: Path, local_name: str, *, original: str) -> Path:
    """Join a local name while preventing escape through existing symlinks."""
    destination = target_dir / local_name
    if not destination.resolve().is_relative_to(target_dir.resolve()):
        raise Cveta2Error(
            f"Небезопасный путь изображения {original!r}: "
            f"назначение находится вне локального кэша {target_dir}"
        )
    return destination


def _download_pending(
    s3_client: S3Client,
    bucket: str,
    pending: list[Transfer],
    stats: DownloadStats,
    progress: _ProgressLabels,
) -> None:
    """Download *pending* transfers, adding the outcome counts to *stats*."""
    ok, failed = run_s3_transfers(
        pending,
        lambda t: _download_one_s3(s3_client, bucket, t.key, t.path),
        lambda t: f"{t.name} (key={t.key})",
        desc=progress.desc,
        unit=progress.unit,
    )
    stats.downloaded += ok
    stats.failed += failed


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

        logger.info(f"Загрузка изображений: {stats.summary()}")
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
        prefix = project_cloud_storage.prefix if project_cloud_storage else ""
        full_key = _canonical_frame_key(prefix, frame_ref)
        local_root = self._ignored_prefix or prefix
        local_name = _local_name_from_key(full_key, local_root, original=frame_ref)
        return _confined_destination(self._target_dir, local_name, original=frame_ref)

    def _filter_cached(
        self,
        image_tasks: dict[str, str],
        stats: DownloadStats,
        project_cloud_storage: CloudStorageInfo | None,
    ) -> dict[str, str]:
        """Remove already-cached images, updating *stats*. Return pending.

        The existence checks run concurrently: on a shared network cache
        each one is a round-trip, and there is one per image in the fetch.
        """
        entries = list(image_tasks.items())
        cached_flags = run_concurrent(
            entries,
            lambda entry: self._dest_path(entry[1], project_cloud_storage).exists(),
            max_workers=Workers.s3,
            catch=(),
            desc="Checking local cache",
            unit="img",
        )
        pending: dict[str, str] = {}
        for (image_name, frame_ref), is_cached in zip(
            entries, cached_flags, strict=True
        ):
            if is_cached is True:
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
        name_to_key = self._resolve_s3_keys(s3_client, project_cloud_storage, pending)
        to_download: list[Transfer] = []
        missing: list[str] = []
        for image_name, frame_ref in pending.items():
            s3_key = name_to_key.get(image_name)
            if s3_key is None:
                missing.append(image_name)
                continue
            dest = self._dest_path(frame_ref, project_cloud_storage)
            to_download.append(Transfer(name=image_name, key=s3_key, path=dest))
        if missing:
            stats.failed += len(missing)
            logger.warning(
                f"Не найдены на S3 ({len(missing)} шт.): "
                f"{', '.join(missing[:_MISSING_PREVIEW_LIMIT])}"
                f"{'...' if len(missing) > _MISSING_PREVIEW_LIMIT else ''}"
            )
        _download_pending(
            s3_client,
            project_cloud_storage.bucket,
            to_download,
            stats,
            _PROJECT_STORAGE_PROGRESS,
        )

    def _resolve_s3_keys(
        self,
        s3_client: S3Client,
        project_cloud_storage: CloudStorageInfo,
        pending: dict[str, str],
    ) -> dict[str, str]:
        """Return ``{image_name: s3_key}`` for the pending images found on S3.

        The frame name CVAT reports is normally the object key below the
        storage prefix, so a small batch can confirm each key with one
        HEAD.  The alternative — and the fallback — is walking the whole
        project prefix, which holds every task's images and is a serial
        chain of round-trips per thousand keys; a fetch of one task used
        to pay for all of it.  Names no direct probe confirms go through
        that listing, which is also what resolves a bare file name
        against a nested key.
        """
        resolved: dict[str, str] = {}
        unresolved = pending
        if len(pending) <= _DIRECT_KEY_PROBE_LIMIT:
            resolved, unresolved = self._probe_expected_keys(
                s3_client, project_cloud_storage, pending
            )
            if not unresolved:
                return resolved
        name_to_key = self._build_project_storage_name_map(
            s3_client,
            project_cloud_storage.bucket,
            project_cloud_storage.prefix,
        )
        for image_name, frame_ref in unresolved.items():
            canonical = _canonical_frame_key(project_cloud_storage.prefix, frame_ref)
            relative = strip_key_prefix(canonical, project_cloud_storage.prefix)
            s3_key = (
                name_to_key.get(relative)
                or name_to_key.get(canonical)
                or name_to_key.get(image_name)
            )
            if s3_key is not None:
                resolved[image_name] = s3_key
        return resolved

    @staticmethod
    def _probe_expected_keys(
        s3_client: S3Client,
        project_cloud_storage: CloudStorageInfo,
        pending: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Split *pending* into images found at their expected key, and the rest.

        Returns ``({image_name: s3_key}, {image_name: frame_ref})``.
        """
        entries = list(pending.items())
        keys = [
            _canonical_frame_key(project_cloud_storage.prefix, frame_ref)
            for _, frame_ref in entries
        ]
        found = run_concurrent(
            keys,
            lambda key: s3_object_exists(s3_client, project_cloud_storage.bucket, key),
            max_workers=Workers.s3,
            catch=(),
            desc="Locating images on S3",
            unit="img",
        )
        resolved: dict[str, str] = {}
        unresolved: dict[str, str] = {}
        for (image_name, frame_ref), key, exists in zip(
            entries, keys, found, strict=True
        ):
            if exists is True:
                resolved[image_name] = key
            else:
                unresolved[image_name] = frame_ref
        return resolved, unresolved

    @staticmethod
    def _build_project_storage_name_map(
        s3_client: S3Client,
        bucket: str,
        prefix: str,
    ) -> dict[str, str]:
        """List objects under prefix; return name -> S3 key (full name + basename).

        The basename entries are what makes the ``image_name`` fallback in
        :meth:`_download_all` work: ``image_name`` is always a bare
        filename (the model validator collapses nested CVAT frame names
        into ``frame_path``).
        """
        pairs = list_s3_objects(s3_client, bucket, prefix)
        return names_with_basename_fallback((name, key) for key, name in pairs)


def _download_one_s3(
    s3_client: S3Client,
    bucket: str,
    key: str,
    dest: Path,
) -> None:
    """Download a single S3 object to *dest*; a failed write leaves nothing behind.

    The cache treats every existing file as complete, so the bytes go
    through a per-writer temp name and reach *dest* only by an atomic
    rename — a disk that fills up mid-write cannot leave a truncated
    image that later runs would skip as cached.
    """
    replace_shared_bytes(dest, s3_get_bytes(s3_client, bucket, key))


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
        if not objects:
            logger.info(f"Нет объектов в s3://{cs_info.bucket}/{cs_info.prefix}")
            return DownloadStats(total=0)

        stats = DownloadStats(total=len(objects))
        local_root = self._ignored_prefix or cs_info.prefix
        safe_objects = [
            (
                key,
                _local_name_from_key(key, local_root, original=name),
            )
            for key, name in objects
        ]
        to_download = [
            Transfer(
                name=name,
                key=key,
                path=_confined_destination(self._target_dir, name, original=name),
            )
            for key, name in safe_objects
            if not _confined_destination(self._target_dir, name, original=name).exists()
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
            _S3_SYNC_PROGRESS,
        )

        logger.info(f"S3 sync: {stats.summary()}")
        return stats

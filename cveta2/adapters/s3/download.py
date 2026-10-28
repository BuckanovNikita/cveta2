"""Download project images from S3 cloud storage attached to CVAT.

When *project_cloud_storage* is provided, all images (including images without
annotations) are downloaded from that storage by name lookup; task
``source_storage`` is not used. When *project_cloud_storage* is None, all
pending images are counted as failed. Already-cached files are skipped.
"""

from typing import TYPE_CHECKING, NamedTuple

from botocore.exceptions import ClientError
from loguru import logger

from cveta2.adapters.execution.concurrency import Workers, run_concurrent
from cveta2.adapters.execution.retry import network_retry
from cveta2.adapters.files.materialization import _confined_destination
from cveta2.adapters.files.shared import ensure_shared_dir, replace_shared_bytes
from cveta2.adapters.s3.types import Transfer
from cveta2.adapters.s3.utils import (
    _NOT_FOUND_CODES,
    S3_TRANSFER_ERRORS,
    _should_retry_s3,
    list_s3_objects,
    make_s3_client,
    run_s3_transfers,
    s3_get_bytes,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.paths import (
    _canonical_frame_key,
    _local_name_from_key,
    _validate_relative_key,
    names_with_basename_fallback,
    strip_key_prefix,
)
from cveta2.domain.storage import CloudStorageInfo, DownloadStats

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.adapters.s3.types import S3Client
    from cveta2.domain.models import ProjectAnnotations


class _ProgressLabels(NamedTuple):
    """Caption and unit noun of one transfer batch's progress bar."""

    desc: "str"
    unit: "str"


_PROJECT_STORAGE_PROGRESS = _ProgressLabels("Downloading from project storage", "img")
_S3_SYNC_PROGRESS = _ProgressLabels("Syncing from S3", "file")

_MISSING_PREVIEW_LIMIT = 10
"""How many not-found image names the warning lists before collapsing the rest."""

_DIRECT_KEY_PROBE_LIMIT = 2000
"""Above this many pending images, list the prefix before downloading.

Small batches download their canonical key immediately; only a missing response
pays for the whole-prefix listing and basename fallback.
"""


def _download_pending(
    s3_client: "S3Client",
    bucket: "str",
    pending: "list[Transfer]",
    stats: "DownloadStats",
    progress: "_ProgressLabels",
) -> "None":
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

    def __init__(
        self, target_dir: "Path", ignored_prefix: "str | None" = None
    ) -> "None":
        """Store the target directory and optional S3 prefix to strip."""
        self._target_dir = target_dir
        self._ignored_prefix = ignored_prefix

    def download(
        self,
        annotations: "ProjectAnnotations",
        project_cloud_storage: "CloudStorageInfo | None" = None,
    ) -> "DownloadStats":
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
        resolved = self._download_all(pending, stats, project_cloud_storage)
        for record in (*annotations.annotations, *annotations.deleted_images):
            key = resolved.get(record.image_name)
            if key is not None:
                record.s3_image_path = key

        logger.info(f"Загрузка изображений: {stats.summary()}")
        return stats

    @staticmethod
    def _collect_unique_images(
        annotations: "ProjectAnnotations",
    ) -> "dict[str, str]":
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
        frame_ref: "str",
        project_cloud_storage: "CloudStorageInfo | None",
    ) -> "Path":
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
        image_tasks: "dict[str, str]",
        stats: "DownloadStats",
        project_cloud_storage: "CloudStorageInfo | None",
    ) -> "dict[str, str]":
        """Remove already-cached images, updating *stats*. Return pending.

        The existence checks run concurrently: on a shared network cache
        each one is a round-trip, and there is one per image in the fetch.
        """
        entries = list(image_tasks.items())
        cached_flags = run_concurrent(
            entries,
            lambda entry: self._dest_path(entry[1], project_cloud_storage).is_file(),
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
        pending: "dict[str, str]",
        stats: "DownloadStats",
        project_cloud_storage: "CloudStorageInfo | None" = None,
    ) -> "dict[str, str]":
        """Download all pending images from project cloud storage by name lookup."""
        if project_cloud_storage is None:
            stats.failed += len(pending)
            if pending:
                logger.warning(
                    "Project cloud storage не задан — все изображения помечены "
                    "как failed. Укажите project_id при вызове download_images."
                )
            return {}
        s3_client = make_s3_client(project_cloud_storage.endpoint_url or None)
        resolved: dict[str, str] = {}
        if len(pending) <= _DIRECT_KEY_PROBE_LIMIT:
            direct = [
                Transfer(
                    name=name,
                    key=_canonical_frame_key(project_cloud_storage.prefix, frame),
                    path=self._dest_path(frame, project_cloud_storage),
                )
                for name, frame in pending.items()
            ]
            absent = _download_image_batch(
                s3_client, project_cloud_storage.bucket, direct, stats
            )
            resolved = {t.name: t.key for t in direct if t.name not in absent}
            pending = {name: pending[name] for name in absent}
            if not pending:
                return resolved
        name_to_key = self._resolve_s3_keys(s3_client, project_cloud_storage, pending)
        to_download: list[Transfer] = []
        missing: list[str] = []
        for image_name in pending:
            s3_key = name_to_key.get(image_name)
            if s3_key is None:
                missing.append(image_name)
                continue
            dest = self._dest_path(f"/{s3_key}", project_cloud_storage)
            if dest.is_file():
                stats.cached += 1
                continue
            to_download.append(Transfer(name=image_name, key=s3_key, path=dest))
        if missing:
            stats.failed += len(missing)
            logger.warning(
                f"Не найдены на S3 ({len(missing)} шт.): "
                f"{', '.join(missing[:_MISSING_PREVIEW_LIMIT])}"
                f"{'...' if len(missing) > _MISSING_PREVIEW_LIMIT else ''}"
            )
        vanished = _download_image_batch(
            s3_client, project_cloud_storage.bucket, to_download, stats
        )
        if vanished:
            stats.failed += len(vanished)
            logger.warning(
                "Объекты исчезли с S3 после listing: "
                f"{', '.join(vanished[:_MISSING_PREVIEW_LIMIT])}"
            )
        return resolved | name_to_key

    def _resolve_s3_keys(
        self,
        s3_client: "S3Client",
        project_cloud_storage: "CloudStorageInfo",
        pending: "dict[str, str]",
    ) -> "dict[str, str]":
        """Resolve pending images by listing, retaining full-key precedence."""
        resolved: dict[str, str] = {}
        name_to_key = self._build_project_storage_name_map(
            s3_client,
            project_cloud_storage.bucket,
            project_cloud_storage.prefix,
        )
        for image_name, frame_ref in pending.items():
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
    def _build_project_storage_name_map(
        s3_client: "S3Client",
        bucket: "str",
        prefix: "str",
    ) -> "dict[str, str]":
        """List objects under prefix; return name -> S3 key (full name + basename).

        The basename entries are what makes the ``image_name`` fallback in
        :meth:`_download_all` work: ``image_name`` is always a bare
        filename (the model validator collapses nested CVAT frame names
        into ``frame_path``).
        """
        pairs = list_s3_objects(s3_client, bucket, prefix)
        return names_with_basename_fallback((name, key) for key, name in pairs)


class _ImageTransferError(Exception):
    """A response body or local write failed after the request succeeded."""


def _retry_image_read(error: BaseException) -> bool:
    """Preserve S3 retries while retaining the phase of a body failure."""
    if isinstance(error, _ImageTransferError):
        return error.__cause__ is not None and _should_retry_s3(error.__cause__)
    return _should_retry_s3(error)


@network_retry(_retry_image_read, label="S3")
def _image_bytes(s3_client: "S3Client", bucket: str, key: str) -> bytes:
    """Read one object per active worker; request failures keep their identity."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    try:
        # The opaque boto3 response owns its streaming-body type. Reading happens
        # inside the retry boundary; no batch of response bodies is retained.
        data: bytes = response["Body"].read()
    except S3_TRANSFER_ERRORS as error:
        raise _ImageTransferError(f"Чтение тела S3 {key}: {error}") from error
    return data


def _download_image(s3_client: "S3Client", bucket: str, transfer: Transfer) -> bool:
    """Return False only for a missing key; abort on other request failures."""
    try:
        data = _image_bytes(s3_client, bucket, transfer.key)
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES:
            return False
        raise
    except KeyError as error:
        # Malformed response fixtures/SDK payloads are counted as transfer
        # failures, as before; they never trigger a missing-key lookup.
        raise _ImageTransferError(f"Некорректный ответ S3 {transfer.key}") from error
    try:
        replace_shared_bytes(transfer.path, data)
    except OSError as error:
        raise _ImageTransferError(f"Запись {transfer.path}: {error}") from error
    return True


def _download_image_batch(
    s3_client: "S3Client", bucket: str, transfers: list[Transfer], stats: DownloadStats
) -> list[str]:
    """Count successes/body/write failures and return missing names in order."""
    outcomes = run_concurrent(
        transfers,
        lambda transfer: _download_image(s3_client, bucket, transfer),
        max_workers=Workers.s3,
        catch=(_ImageTransferError,),
        desc=_PROJECT_STORAGE_PROGRESS.desc,
        unit=_PROJECT_STORAGE_PROGRESS.unit,
    )
    missing: list[str] = []
    for transfer, outcome in zip(transfers, outcomes, strict=True):
        if isinstance(outcome, _ImageTransferError):
            stats.failed += 1
            logger.error(
                f"Не удалось загрузить {transfer.name} (key={transfer.key}): {outcome}"
            )
        elif outcome is False:
            missing.append(transfer.name)
        else:
            stats.downloaded += 1
    return missing


def _download_one_s3(
    s3_client: "S3Client",
    bucket: "str",
    key: "str",
    dest: "Path",
) -> "None":
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

    def __init__(
        self, target_dir: "Path", ignored_prefix: "str | None" = None
    ) -> "None":
        """Store the target directory and optional S3 prefix to strip."""
        self._target_dir = target_dir
        self._ignored_prefix = ignored_prefix

    def sync(self, cs_info: "CloudStorageInfo") -> "DownloadStats":
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
        transfers: list[Transfer] = []
        destinations: dict[Path, str] = {}
        for key, name in objects:
            _validate_relative_key(key, original=key)
            local_name = _local_name_from_key(key, local_root, original=key)
            destination = _confined_destination(
                self._target_dir, local_name, original=key
            )
            resolved = destination.resolve()
            if resolved in destinations:
                raise Cveta2Error(
                    f"Объекты S3 {destinations[resolved]!r} и {key!r} "
                    f"имеют одно назначение {destination}"
                )
            destinations[resolved] = key
            transfers.append(Transfer(name=name, key=key, path=destination))
        # A file destination cannot also be a parent of another destination.
        for destination in destinations:
            if any(parent in destinations for parent in destination.parents):
                raise Cveta2Error(
                    f"Конфликт назначений S3: {destination} вложен в другой файл"
                )
        to_download = [t for t in transfers if not t.path.is_file()]
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

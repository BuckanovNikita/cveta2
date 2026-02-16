"""Download project images from S3 cloud storage attached to CVAT.

Auto-detects the cloud storage from CVAT task ``source_storage`` metadata,
then downloads images directly via boto3.  Already-cached files are skipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

import boto3
from loguru import logger
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tqdm import tqdm

if TYPE_CHECKING:
    from cveta2.models import ProjectAnnotations


# ---------------------------------------------------------------------------
# Cloud storage info
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Download stats
# ---------------------------------------------------------------------------


class DownloadStats(BaseModel):
    """Result counters for an image download run."""

    downloaded: int = 0
    cached: int = 0
    failed: int = 0
    total: int = 0


# ---------------------------------------------------------------------------
# S3 retry decorator
# ---------------------------------------------------------------------------

_s3_retry = retry(
    retry=retry_if_exception_type((OSError, ConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


# ---------------------------------------------------------------------------
# Image downloader
# ---------------------------------------------------------------------------


def _build_s3_key(prefix: str, frame_name: str) -> str:
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


class ImageDownloader:
    """Download project images from S3 into a user-specified directory.

    Images are saved directly as ``target_dir / image_name`` — no
    additional subdirectories are created.
    """

    def __init__(self, target_dir: Path) -> None:
        """Store the target directory for image downloads."""
        self._target_dir = target_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(
        self,
        sdk_client: Any,  # noqa: ANN401
        annotations: ProjectAnnotations,
        project_cloud_storage: CloudStorageInfo | None = None,
    ) -> DownloadStats:
        """Download images referenced in *annotations*.

        Returns counters of downloaded / cached / failed images.
        If *project_cloud_storage* is set, images from tasks without
        their own storage are searched in the project storage by name.
        """
        image_tasks = self._collect_unique_images(annotations)
        if not image_tasks:
            return DownloadStats(total=0)

        stats = DownloadStats(total=len(image_tasks))
        pending = self._filter_cached(image_tasks, stats)
        if not pending:
            logger.info(
                f"Все {stats.cached} изображений уже загружены в {self._target_dir}"
            )
            return stats

        self._target_dir.mkdir(parents=True, exist_ok=True)
        self._download_all(sdk_client, pending, stats, project_cloud_storage)

        logger.info(
            f"Загрузка изображений: {stats.downloaded} новых, "
            f"{stats.cached} из кэша, {stats.failed} ошибок "
            f"(всего {stats.total})"
        )
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_unique_images(
        annotations: ProjectAnnotations,
    ) -> dict[str, int]:
        """Return ``{image_name: task_id}`` for unique images.

        First occurrence wins (keeps a stable task_id per image).
        Deleted images are not included (they live in
        ``deleted_images``, not ``annotations``).
        """
        result: dict[str, int] = {}
        for record in annotations.annotations:
            if record.image_name not in result:
                result[record.image_name] = record.task_id
        return result

    def _filter_cached(
        self,
        image_tasks: dict[str, int],
        stats: DownloadStats,
    ) -> dict[str, int]:
        """Remove already-cached images, updating *stats*. Return pending."""
        pending: dict[str, int] = {}
        for image_name, task_id in image_tasks.items():
            if (self._target_dir / image_name).exists():
                stats.cached += 1
            else:
                pending[image_name] = task_id
        return pending

    def _download_all(
        self,
        sdk_client: Any,  # noqa: ANN401
        pending: dict[str, int],
        stats: DownloadStats,
        project_cloud_storage: CloudStorageInfo | None = None,
    ) -> None:
        """Resolve cloud storages, create S3 clients, download pending images."""
        task_cs = self._resolve_task_cloud_storages(
            sdk_client, pending, project_cloud_storage
        )
        s3_clients = self._build_s3_clients(task_cs, project_cloud_storage)
        fallback_pending = self._download_from_task_storage(
            pending, task_cs, s3_clients, stats
        )
        self._download_from_project_fallback(
            fallback_pending, project_cloud_storage, s3_clients, stats
        )

    def _resolve_task_cloud_storages(
        self,
        sdk_client: Any,  # noqa: ANN401
        pending: dict[str, int],
        project_cloud_storage: CloudStorageInfo | None,
    ) -> dict[int, CloudStorageInfo | None]:
        """Resolve cloud storage per task_id; warn when no storage and no fallback."""
        cs_cache: dict[int, CloudStorageInfo] = {}
        task_cs: dict[int, CloudStorageInfo | None] = {}
        for task_id in set(pending.values()):
            cs_info = self.detect_cloud_storage(sdk_client, task_id, cs_cache)
            task_cs[task_id] = cs_info
            if cs_info is None and project_cloud_storage is None:
                count = sum(1 for t in pending.values() if t == task_id)
                logger.warning(
                    f"Task {task_id} не имеет cloud storage — "
                    f"пропускаем {count} изображений"
                )
        return task_cs

    def _build_s3_clients(
        self,
        task_cs: dict[int, CloudStorageInfo | None],
        project_cloud_storage: CloudStorageInfo | None,
    ) -> dict[str, Any]:
        """Build one boto3 S3 client per unique (endpoint, bucket)."""
        s3_clients: dict[str, Any] = {}
        for cs_info in task_cs.values():
            if cs_info is None:
                continue
            key = f"{cs_info.endpoint_url}|{cs_info.bucket}"
            if key not in s3_clients:
                s3_clients[key] = boto3.Session().client(
                    "s3",
                    endpoint_url=cs_info.endpoint_url or None,
                )
        if project_cloud_storage is not None:
            ep_key = (
                f"{project_cloud_storage.endpoint_url}|{project_cloud_storage.bucket}"
            )
            if ep_key not in s3_clients:
                s3_clients[ep_key] = boto3.Session().client(
                    "s3",
                    endpoint_url=project_cloud_storage.endpoint_url or None,
                )
        return s3_clients

    def _download_from_task_storage(
        self,
        pending: dict[str, int],
        task_cs: dict[int, CloudStorageInfo | None],
        s3_clients: dict[str, Any],
        stats: DownloadStats,
    ) -> dict[str, int]:
        """Download from task-level storage; return remaining as fallback_pending."""
        fallback_pending: dict[str, int] = {}
        for image_name, task_id in pending.items():
            cs_info = task_cs.get(task_id)
            if cs_info is None:
                fallback_pending[image_name] = task_id
                continue
            ep_key = f"{cs_info.endpoint_url}|{cs_info.bucket}"
            s3_key = _build_s3_key(cs_info.prefix, image_name)
            dest = self._target_dir / image_name
            try:
                self._download_one(s3_clients[ep_key], cs_info.bucket, s3_key, dest)
                stats.downloaded += 1
            except (OSError, ConnectionError, KeyError):
                logger.exception(f"Не удалось загрузить {image_name} (key={s3_key})")
                stats.failed += 1
        return fallback_pending

    def _download_from_project_fallback(
        self,
        fallback_pending: dict[str, int],
        project_cloud_storage: CloudStorageInfo | None,
        s3_clients: dict[str, Any],
        stats: DownloadStats,
    ) -> None:
        """Download fallback images from project storage by name lookup."""
        if project_cloud_storage is None:
            for _ in fallback_pending:
                stats.failed += 1
            return
        if not fallback_pending:
            return
        ep_key = f"{project_cloud_storage.endpoint_url}|{project_cloud_storage.bucket}"
        name_to_key = self._build_project_storage_name_map(
            s3_clients[ep_key],
            project_cloud_storage.bucket,
            project_cloud_storage.prefix,
        )
        for image_name in tqdm(
            fallback_pending,
            desc="Downloading from project storage",
            unit="img",
            leave=False,
        ):
            s3_key: str | None = name_to_key.get(image_name) or name_to_key.get(
                Path(image_name).name
            )
            if s3_key is None:
                stats.failed += 1
                continue
            dest = self._target_dir / image_name
            try:
                self._download_one(
                    s3_clients[ep_key],
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
        s3_client: Any,  # noqa: ANN401
        bucket: str,
        prefix: str,
    ) -> dict[str, str]:
        """List objects under prefix; return name -> S3 key (full name + basename)."""
        pairs = _list_s3_objects(s3_client, bucket, prefix)
        name_to_key: dict[str, str] = {}
        for key, name in pairs:
            name_to_key[name] = key
            base = Path(name).name
            if base not in name_to_key:
                name_to_key[base] = key
        return name_to_key

    @staticmethod
    def detect_cloud_storage(
        sdk_client: Any,  # noqa: ANN401
        task_id: int,
        cs_cache: dict[int, CloudStorageInfo],
    ) -> CloudStorageInfo | None:
        """Detect cloud storage for a task via its ``source_storage``.

        Uses ``getattr`` because the CVAT SDK task object may expose
        ``source_storage`` as a dict or typed model depending on SDK
        version.  This is an intentional exception to the project style
        rule "avoid getattr" (see CLAUDE.md).
        """
        task = sdk_client.tasks.retrieve(task_id)

        source_storage = getattr(task, "source_storage", None)
        if source_storage is None:
            return None

        if isinstance(source_storage, dict):
            cs_id: int | None = source_storage.get("cloud_storage_id")
        else:
            cs_id = getattr(source_storage, "cloud_storage_id", None)

        if cs_id is None:
            return None

        if cs_id in cs_cache:
            return cs_cache[cs_id]

        cs_api = sdk_client.api_client.cloudstorages_api
        cs_raw, _ = cs_api.retrieve(cs_id)
        cs_info = parse_cloud_storage(cs_raw)
        cs_cache[cs_id] = cs_info
        logger.trace(
            f"Cloud storage #{cs_info.id}: bucket={cs_info.bucket}, "
            f"prefix={cs_info.prefix}, endpoint={cs_info.endpoint_url}"
        )
        return cs_info

    @staticmethod
    @_s3_retry
    def _download_one(
        s3_client: Any,  # noqa: ANN401
        bucket: str,
        key: str,
        dest: Path,
    ) -> None:
        """Download a single S3 object to *dest*."""
        _download_one_s3(s3_client, bucket, key, dest)


# ---------------------------------------------------------------------------
# Shared S3 helpers
# ---------------------------------------------------------------------------


@_s3_retry
def _download_one_s3(
    s3_client: Any,  # noqa: ANN401
    bucket: str,
    key: str,
    dest: Path,
) -> None:
    """Download a single S3 object to *dest*."""
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    data: bytes = resp["Body"].read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _list_s3_objects(
    s3_client: Any,  # noqa: ANN401
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
            # Strip prefix to get local file name
            name = key[len(prefix) :].lstrip("/") if prefix else key
            if name:  # skip empty (the prefix directory marker itself)
                objects.append((key, name))
        if not resp.get("IsTruncated"):
            break
        kwargs["ContinuationToken"] = resp["NextContinuationToken"]
    return objects


# ---------------------------------------------------------------------------
# S3 sync (full prefix → local directory)
# ---------------------------------------------------------------------------


class S3Syncer:
    """Sync all objects under an S3 cloud storage prefix to a local directory.

    Unlike :class:`ImageDownloader` which downloads only images referenced
    in annotations, this class lists **all** objects in the S3 prefix and
    downloads any that are missing locally.  It never deletes local files
    and never uploads to S3.
    """

    def __init__(self, target_dir: Path) -> None:
        """Store the target directory for synced files."""
        self._target_dir = target_dir

    def sync(self, cs_info: CloudStorageInfo) -> DownloadStats:
        """List all objects under *cs_info* prefix and download missing ones.

        Returns counters of downloaded / cached / failed files.
        """
        s3 = boto3.Session().client(
            "s3",
            endpoint_url=cs_info.endpoint_url or None,
        )
        objects = _list_s3_objects(s3, cs_info.bucket, cs_info.prefix)
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

"""Download project images from S3 cloud storage attached to CVAT.

Auto-detects the cloud storage from CVAT task ``source_storage`` metadata,
then downloads images directly via boto3.  Already-cached files are skipped.
"""

from __future__ import annotations

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
    from pathlib import Path

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
    ) -> DownloadStats:
        """Download images referenced in *annotations*.

        Returns counters of downloaded / cached / failed images.
        """
        frames = self._collect_frames(annotations)
        if not frames:
            return DownloadStats(total=0)

        stats = DownloadStats(total=len(frames))
        to_download = self._partition_cached(frames, stats)
        if not to_download:
            logger.info(
                f"Все {stats.cached} изображений уже загружены в {self._target_dir}"
            )
            return stats

        task_cs = self._resolve_cloud_storages(sdk_client, to_download, stats)
        s3_clients = self._create_s3_clients(task_cs)
        self._target_dir.mkdir(parents=True, exist_ok=True)
        self._execute_downloads(to_download, task_cs, s3_clients, stats)

        logger.info(
            f"Загрузка изображений: {stats.downloaded} новых, "
            f"{stats.cached} из кэша, {stats.failed} ошибок "
            f"(всего {stats.total})"
        )
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _partition_cached(
        self,
        frames: list[tuple[int, int, str]],
        stats: DownloadStats,
    ) -> dict[int, list[tuple[int, str]]]:
        """Split frames into cached (update stats) and to-download groups."""
        to_download: dict[int, list[tuple[int, str]]] = {}
        for task_id, frame_id, image_name in frames:
            dest = self._target_dir / image_name
            if dest.exists():
                stats.cached += 1
                continue
            to_download.setdefault(task_id, []).append((frame_id, image_name))
        return to_download

    @staticmethod
    def _resolve_cloud_storages(
        sdk_client: Any,  # noqa: ANN401
        to_download: dict[int, list[tuple[int, str]]],
        stats: DownloadStats,
    ) -> dict[int, CloudStorageInfo]:
        """Detect cloud storage for each task, updating *stats* on failure."""
        cs_cache: dict[int, CloudStorageInfo] = {}
        task_cs: dict[int, CloudStorageInfo] = {}
        for task_id, frame_list in to_download.items():
            cs_info = ImageDownloader._detect_cloud_storage(
                sdk_client, task_id, cs_cache
            )
            if cs_info is None:
                logger.warning(
                    f"Task {task_id} не имеет cloud storage — "
                    f"пропускаем {len(frame_list)} изображений"
                )
                stats.failed += len(frame_list)
                continue
            task_cs[task_id] = cs_info
        return task_cs

    @staticmethod
    def _create_s3_clients(
        task_cs: dict[int, CloudStorageInfo],
    ) -> dict[str, Any]:
        """Create one boto3 S3 client per unique (endpoint, bucket) pair."""
        s3_clients: dict[str, Any] = {}
        for cs_info in task_cs.values():
            key = f"{cs_info.endpoint_url}|{cs_info.bucket}"
            if key not in s3_clients:
                s3_clients[key] = boto3.Session().client(
                    "s3",
                    endpoint_url=cs_info.endpoint_url or None,
                )
        return s3_clients

    def _execute_downloads(
        self,
        to_download: dict[int, list[tuple[int, str]]],
        task_cs: dict[int, CloudStorageInfo],
        s3_clients: dict[str, Any],
        stats: DownloadStats,
    ) -> None:
        """Download all pending images, updating *stats* in place."""
        items: list[tuple[str, str, str, str]] = []
        for task_id, frame_list in to_download.items():
            cs_info = task_cs.get(task_id)
            if cs_info is None:
                continue
            ep_key = f"{cs_info.endpoint_url}|{cs_info.bucket}"
            for _fid, image_name in frame_list:
                s3_key = _build_s3_key(cs_info.prefix, image_name)
                items.append((s3_key, cs_info.bucket, ep_key, image_name))

        for s3_key, bucket, ep_key, image_name in tqdm(
            items, desc="Downloading images", unit="img", leave=False
        ):
            s3 = s3_clients[ep_key]
            dest = self._target_dir / image_name
            try:
                self._download_one(s3, bucket, s3_key, dest)
                stats.downloaded += 1
            except (OSError, ConnectionError, KeyError):
                logger.exception(f"Не удалось загрузить {image_name} (key={s3_key})")
                stats.failed += 1

    @staticmethod
    def _collect_frames(
        annotations: ProjectAnnotations,
    ) -> list[tuple[int, int, str]]:
        """Return deduplicated (task_id, frame_id, image_name) list.

        Deleted images are excluded.
        """
        seen: set[tuple[int, int]] = set()
        result: list[tuple[int, int, str]] = []

        for ann in annotations.annotations:
            key = (ann.task_id, ann.frame_id)
            if key not in seen:
                seen.add(key)
                result.append((ann.task_id, ann.frame_id, ann.image_name))

        for img in annotations.images_without_annotations:
            key = (img.task_id, img.frame_id)
            if key not in seen:
                seen.add(key)
                result.append((img.task_id, img.frame_id, img.image_name))

        return result

    @staticmethod
    def _detect_cloud_storage(
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
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        data: bytes = resp["Body"].read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

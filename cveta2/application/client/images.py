"""Image retrieval from S3: targeted downloads and full-prefix sync."""

from typing import TYPE_CHECKING

from loguru import logger

from cveta2.application.client.read import _ReadMixin
from cveta2.domain.storage import DownloadStats

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.domain.models import ProjectAnnotations
    from cveta2.domain.storage import CloudStorageInfo


class _ImageMixin(_ReadMixin):
    """Download annotated images and sync a project's full S3 prefix."""

    def download_images(
        self,
        annotations: "ProjectAnnotations",
        target_dir: "Path",
        project_id: int | None = None,
        project_cloud_storage: "CloudStorageInfo | None" = None,
        ignored_prefix: str | None = None,
    ) -> DownloadStats:
        """Download project images from S3 cloud storage into *target_dir*.

        Requires an active context manager (``with CvatClient(...) as c:``).
        Images are saved flat as ``target_dir / image_name``; with
        *ignored_prefix* set, the local layout mirrors the S3 key below
        that prefix.  Already-cached files are skipped.

        Images are always downloaded from the **project** cloud storage
        (project's ``source_storage`` via :meth:`detect_project_cloud_storage`
        when *project_id* is given). Per-task storage is not used. If
        *project_id* is not given, project storage cannot be resolved and
        all images will be reported as failed.
        """
        if project_cloud_storage is None and project_id is not None:
            project_cloud_storage = self.detect_project_cloud_storage(project_id)
        return self._images.download(
            annotations,
            target_dir,
            project_cloud_storage=project_cloud_storage,
            ignored_prefix=ignored_prefix,
        )

    def sync_project_images(
        self,
        project_id: int,
        target_dir: "Path",
        project_cloud_storage: "CloudStorageInfo | None" = None,
        ignored_prefix: str | None = None,
    ) -> DownloadStats:
        """Sync all S3 objects for *project_id* into *target_dir*.

        Lists every object under the project's cloud storage prefix and
        downloads those missing locally.  Never deletes from S3 or syncs
        in reverse.

        When *project_cloud_storage* is provided, uses it; otherwise
        calls :meth:`detect_project_cloud_storage`(project_id).

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        if project_cloud_storage is None:
            project_cloud_storage = self.detect_project_cloud_storage(project_id)
        cs_info = project_cloud_storage
        if cs_info is None:
            logger.warning(
                f"Проект {project_id}: cloud storage не найден — "
                f"пропускаем синхронизацию."
            )
            return DownloadStats(total=0)

        logger.info(
            f"Проект {project_id}: синхронизация из "
            f"s3://{cs_info.bucket}/{cs_info.prefix} → {target_dir}"
        )
        return self._images.sync(cs_info, target_dir, ignored_prefix=ignored_prefix)

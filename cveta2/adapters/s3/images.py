"""S3 implementation of the application image retrieval port."""

from pathlib import Path

from cveta2.adapters.s3.download import ImageDownloader, S3Syncer
from cveta2.domain.models import ProjectAnnotations
from cveta2.domain.storage import CloudStorageInfo, DownloadStats


class S3ImageReader:
    """Construct transfer adapters at the filesystem/network boundary."""

    def download(
        self,
        annotations: ProjectAnnotations,
        target_dir: Path,
        project_cloud_storage: CloudStorageInfo | None = None,
        ignored_prefix: str | None = None,
    ) -> DownloadStats:
        """Download the annotated images through the existing S3 transfer."""
        return ImageDownloader(target_dir, ignored_prefix=ignored_prefix).download(
            annotations, project_cloud_storage=project_cloud_storage
        )

    def sync(
        self,
        cs_info: CloudStorageInfo,
        target_dir: Path,
        ignored_prefix: str | None = None,
    ) -> DownloadStats:
        """Sync the project prefix through the existing S3 transfer."""
        return S3Syncer(target_dir, ignored_prefix=ignored_prefix).sync(cs_info)

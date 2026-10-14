"""Application-owned image retrieval boundary."""

from pathlib import Path
from typing import Protocol

from cveta2.domain.models import ProjectAnnotations
from cveta2.domain.storage import CloudStorageInfo, DownloadStats


class ImageReadPort(Protocol):
    """Retrieve project images while preserving per-object transfer outcomes."""

    def download(
        self,
        annotations: ProjectAnnotations,
        target_dir: Path,
        project_cloud_storage: CloudStorageInfo | None = None,
        ignored_prefix: str | None = None,
    ) -> DownloadStats:
        """Retrieve images with per-object statistics."""
        ...

    def sync(
        self,
        cs_info: CloudStorageInfo,
        target_dir: Path,
        ignored_prefix: str | None = None,
    ) -> DownloadStats:
        """Retrieve images with per-object statistics."""
        ...

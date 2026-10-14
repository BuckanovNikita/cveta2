"""Compatible public exports from canonical implementations."""

from cveta2.adapters.cvat.storage import (
    parse_cloud_storage,
)
from cveta2.adapters.s3.download import (
    ImageDownloader,
    S3Syncer,
)
from cveta2.domain.storage import (
    CloudStorageInfo,
    DownloadStats,
)

__all__ = [
    "CloudStorageInfo",
    "DownloadStats",
    "ImageDownloader",
    "S3Syncer",
    "parse_cloud_storage",
]

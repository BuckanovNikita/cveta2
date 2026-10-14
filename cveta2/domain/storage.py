"""Neutral storage identity and transfer outcomes."""

from pydantic import BaseModel


class CloudStorageInfo(BaseModel):
    """Parsed cloud storage metadata from CVAT."""

    id: int
    bucket: str
    prefix: str
    endpoint_url: str


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


class UploadStats(BaseModel):
    """Result counters for an image upload run."""

    uploaded: int = 0
    skipped_existing: int = 0
    failed: int = 0
    total: int = 0

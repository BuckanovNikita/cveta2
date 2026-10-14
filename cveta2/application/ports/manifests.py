"""Durable upload checkpoint persistence."""

from typing import Protocol

from cveta2.domain.storage import CloudStorageInfo
from cveta2.domain.upload import UploadManifest


class ManifestStore(Protocol):
    """Persist upload identity and mandatory recovery checkpoints."""

    def load(
        self, project_id: int, fingerprint: str, *, host: str
    ) -> UploadManifest | None:
        """Read the matching recovery manifest, returning None when absent."""
        ...

    def save(self, manifest: UploadManifest, *, required: bool = False) -> None:
        """Persist state before continuing across mandatory checkpoints."""
        ...

    def list_for_project(self, project_id: int, *, host: str) -> list[UploadManifest]:
        """List readable unfinished uploads for the requested server/project."""
        ...

    def delete(
        self,
        project_id: int,
        fingerprint: str,
        *,
        host: str,
        task_id: int | None = None,
    ) -> None:
        """Remove the completed upload checkpoint."""
        ...

    def new(  # noqa: PLR0913, PLR0917
        self,
        dataset_path: str,
        fingerprint: str,
        project_id: int,
        task_name: str,
        cs_info: CloudStorageInfo,
        name_to_server_file: dict[str, str],
        task_image_names: list[str],
        *,
        host: str,
        intent_complete: bool = False,
    ) -> UploadManifest:
        """Create an upload manifest with the adapter-provided timestamp."""
        ...

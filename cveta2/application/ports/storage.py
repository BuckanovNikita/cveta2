"""Image staging storage contract without SDK ownership."""

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from cveta2.domain.storage import CloudStorageInfo, UploadStats


class UploadStorage(Protocol):
    """Stage named images in remote storage with pinned mapping support."""

    def mapping(
        self,
        cs_info: CloudStorageInfo,
        image_names: Iterable[str],
        *,
        pinned: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], set[str]]:
        """Resolve remote frame names while preserving pinned assignments."""
        ...

    def upload(
        self,
        cs_info: CloudStorageInfo,
        images: dict[str, Path],
        name_to_server_file: dict[str, str],
        existing_keys: set[str],
    ) -> UploadStats:
        """Transfer images and report per-object outcomes."""
        ...

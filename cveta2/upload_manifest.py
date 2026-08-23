"""Crash record of an in-flight upload, so ``--resume`` can pick it up.

The manifest holds *intent and identity*: which task id was created, and
what the run had already decided (the frozen ``YYYY-MM`` folder assignment
and the frame order). It is deliberately not a record of what succeeded —
the failure being recovered from is precisely the client losing track of
what the server did, so every stage decision comes from reading CVAT back.

Layout and durability follow ``task_cache``: a versioned pydantic envelope,
written to a temp file and renamed into place, under an XDG cache root.
"""

from __future__ import annotations

import hashlib
import os
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, ValidationError

from cveta2.fs_utils import default_cache_base, ensure_shared_dir, write_shared_bytes
from cveta2.image_downloader import CloudStorageInfo

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

MANIFEST_SCHEMA_VERSION = 1

_FINGERPRINT_LENGTH = 16


class UploadManifest(BaseModel):
    """One unfinished upload, keyed by what it was uploading."""

    schema_version: int
    started_at: str
    dataset_path: str
    fingerprint: str
    project_id: int
    task_name: str
    cs_info: CloudStorageInfo
    # Frozen because _assign_month_folder reads the clock: a resume that
    # crossed a month boundary would otherwise place the images it still
    # owes into a different folder than the frame order already promised.
    name_to_server_file: dict[str, str]
    task_image_names: list[str]
    task_id: int | None = None

    def describe(self) -> str:
        """One line naming what this manifest was uploading, for a mismatch."""
        return (
            f"{self.dataset_path} → задача {self.task_name!r} "
            f"({len(self.task_image_names)} изображений, "
            f"task_id={self.task_id if self.task_id is not None else '—'}, "
            f"начата {self.started_at})"
        )


def compute_fingerprint(
    image_names: Iterable[str],
    deleted_names: Iterable[str],
    labels: Sequence[str],
) -> str:
    """Identify an upload by what it puts in the task, not by how it was invoked.

    Two runs of the same CSV with the same label selection resume each
    other; a different frame set is a different upload, and continuing one
    from the other's task would bind the wrong images.
    """
    digest = hashlib.sha256()
    for part in (sorted(image_names), sorted(deleted_names), sorted(labels)):
        digest.update(repr(part).encode())
    return digest.hexdigest()[:_FINGERPRINT_LENGTH]


def get_upload_manifest_dir(project_id: int) -> Path:
    """Return the directory holding a project's unfinished upload manifests."""
    return default_cache_base() / "uploads" / f"project_{project_id}"


def save_manifest(manifest: UploadManifest) -> None:
    """Write *manifest* atomically; never fail the upload over bookkeeping."""
    directory = get_upload_manifest_dir(manifest.project_id)
    target = directory / f"{manifest.fingerprint}.json"
    try:
        ensure_shared_dir(directory)
        writer = f"{os.getpid()}-{threading.get_ident()}"
        tmp_path = directory / f"{target.name}.tmp{writer}"
        write_shared_bytes(tmp_path, manifest.model_dump_json().encode())
        tmp_path.replace(target)
    except OSError as e:
        logger.warning(
            f"Не удалось сохранить состояние загрузки ({e}) — "
            f"команда --resume для этого запуска будет недоступна."
        )


def load_manifest(project_id: int, fingerprint: str) -> UploadManifest | None:
    """Return the manifest for *fingerprint*, or None when absent or stale."""
    path = get_upload_manifest_dir(project_id) / f"{fingerprint}.json"
    return _read_manifest(path)


def list_manifests(project_id: int) -> list[UploadManifest]:
    """Return every readable manifest for *project_id*, newest first."""
    directory = get_upload_manifest_dir(project_id)
    if not directory.is_dir():
        return []
    found = [_read_manifest(path) for path in sorted(directory.glob("*.json"))]
    return sorted(
        (m for m in found if m is not None),
        key=lambda m: m.started_at,
        reverse=True,
    )


def delete_manifest(project_id: int, fingerprint: str) -> None:
    """Drop the manifest once its upload has finished."""
    path = get_upload_manifest_dir(project_id) / f"{fingerprint}.json"
    path.unlink(missing_ok=True)


def new_manifest(  # noqa: PLR0913, PLR0917
    dataset_path: str,
    fingerprint: str,
    project_id: int,
    task_name: str,
    cs_info: CloudStorageInfo,
    name_to_server_file: dict[str, str],
    task_image_names: list[str],
) -> UploadManifest:
    """Build a manifest for an upload that is about to touch CVAT."""
    return UploadManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        started_at=datetime.now(timezone.utc).isoformat(),
        dataset_path=dataset_path,
        fingerprint=fingerprint,
        project_id=project_id,
        task_name=task_name,
        cs_info=cs_info,
        name_to_server_file=name_to_server_file,
        task_image_names=task_image_names,
    )


def _read_manifest(path: Path) -> UploadManifest | None:
    """Parse one manifest file, treating anything unreadable as absent."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.info(f"Не удалось прочитать состояние загрузки {path}: {e}")
        return None
    try:
        manifest = UploadManifest.model_validate_json(raw)
    except ValidationError as e:
        logger.info(f"Состояние загрузки {path} не распознано ({e}) — игнорируем.")
        return None
    if manifest.schema_version != MANIFEST_SCHEMA_VERSION:
        logger.info(
            f"Состояние загрузки {path} записано другой версией "
            f"({manifest.schema_version} вместо {MANIFEST_SCHEMA_VERSION}) — "
            f"игнорируем."
        )
        return None
    return manifest

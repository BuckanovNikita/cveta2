"""Atomic filesystem persistence of upload recovery manifests."""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from cveta2.adapters.files.shared import default_cache_base, replace_shared_bytes
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.storage import CloudStorageInfo
from cveta2.domain.upload import (
    MANIFEST_SCHEMA_VERSION,
    UploadManifest,
    normalize_upload_host,
)
from cveta2.domain.upload import (
    new_manifest as build_manifest,
)


def get_upload_manifest_dir(project_id: int, *, host: str) -> Path:
    """Return the directory holding a project's unfinished upload manifests."""
    server = hashlib.sha256(normalize_upload_host(host).encode()).hexdigest()[:16]
    return default_cache_base() / "uploads" / server / f"project_{project_id}"


def save_manifest(manifest: UploadManifest, *, required: bool = False) -> None:
    """Persist recovery state; required checkpoints stop writes on failure."""
    target = (
        get_upload_manifest_dir(manifest.project_id, host=manifest.host)
        / f"{manifest.fingerprint}.json"
    )
    try:
        replace_shared_bytes(target, manifest.model_dump_json().encode())
    except OSError as e:
        if required:
            raise Cveta2Error(
                f"Не удалось сохранить обязательное состояние загрузки "
                f"(task_id={manifest.task_id}): {e}. Следующая запись в CVAT "
                "не выполнена; проверьте сохранённое состояние перед продолжением."
            ) from e
        logger.warning(
            f"Не удалось сохранить состояние загрузки ({e}) — "
            f"команда --resume для этого запуска будет недоступна."
        )


def load_manifest(
    project_id: int, fingerprint: str, *, host: str
) -> UploadManifest | None:
    """Return the manifest for *fingerprint*, or None when absent or stale."""
    path = get_upload_manifest_dir(project_id, host=host) / f"{fingerprint}.json"
    manifest = _read_manifest(path)
    if manifest is None:
        return None
    if (
        manifest.host != normalize_upload_host(host)
        or manifest.project_id != project_id
        or manifest.fingerprint != fingerprint
    ):
        logger.warning(
            f"Состояние загрузки {path} относится к другой загрузке — игнорируем."
        )
        return None
    return manifest


def list_manifests(project_id: int, *, host: str) -> list[UploadManifest]:
    """Return every readable manifest for *project_id*, newest first."""
    directory = get_upload_manifest_dir(project_id, host=host)
    if not directory.is_dir():
        return []
    found = [
        load_manifest(project_id, path.stem, host=host)
        for path in sorted(directory.glob("*.json"))
    ]
    return sorted(
        (m for m in found if m is not None),
        key=lambda m: m.started_at,
        reverse=True,
    )


def delete_manifest(
    project_id: int, fingerprint: str, *, host: str, task_id: int | None = None
) -> None:
    """Drop the manifest once its upload has finished."""
    path = get_upload_manifest_dir(project_id, host=host) / f"{fingerprint}.json"
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            f"Загрузка в задачу {task_id if task_id is not None else '—'} завершена; "
            f"не удалось удалить устаревшее состояние {path}: {exc}. "
            "Повторная загрузка не требуется."
        )


def new_manifest(  # noqa: PLR0913, PLR0917
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
    """Build a manifest for an upload that is about to touch CVAT."""
    return build_manifest(
        dataset_path,
        fingerprint,
        project_id,
        task_name,
        cs_info,
        name_to_server_file,
        task_image_names,
        host=host,
        intent_complete=intent_complete,
        started_at=datetime.now(timezone.utc).isoformat(),
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


class LocalManifestStore:
    """Persist manifests with the existing atomic/checkpoint behavior."""

    load = staticmethod(load_manifest)
    save = staticmethod(save_manifest)
    list_for_project = staticmethod(list_manifests)
    delete = staticmethod(delete_manifest)
    new = staticmethod(new_manifest)

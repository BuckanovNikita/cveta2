"""Atomic filesystem persistence of upload recovery manifests."""

import hashlib
import importlib
import os
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from loguru import logger
from pydantic import ValidationError

from cveta2.adapters.files.shared import (
    FILE_MODE,
    default_cache_base,
    ensure_shared_dir,
    replace_shared_bytes,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.storage import CloudStorageInfo
from cveta2.domain.upload import (
    MANIFEST_SCHEMA_VERSION,
    UploadInProgressError,
    UploadManifest,
    normalize_upload_host,
)
from cveta2.domain.upload import (
    new_manifest as build_manifest,
)


def _load_fcntl() -> ModuleType | None:
    """Return the ``fcntl`` module, or None where the platform lacks it (Windows)."""
    try:
        return importlib.import_module("fcntl")
    except ImportError:
        return None


fcntl = _load_fcntl()


def get_upload_manifest_dir(project_id: int, *, host: str) -> Path:
    """Return the directory holding a project's unfinished upload manifests."""
    server = hashlib.sha256(normalize_upload_host(host).encode()).hexdigest()[:16]
    return default_cache_base() / "uploads" / server / f"project_{project_id}"


def get_manifest_path(project_id: int, fingerprint: str, *, host: str) -> Path:
    """Return the file holding the manifest of one unfinished upload."""
    return get_upload_manifest_dir(project_id, host=host) / f"{fingerprint}.json"


def save_manifest(manifest: UploadManifest, *, required: bool = False) -> None:
    """Persist recovery state; required checkpoints stop writes on failure."""
    target = get_manifest_path(manifest.project_id, manifest.fingerprint, host=manifest.host)
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
            f"Не удалось сохранить состояние загрузки ({e}) — команда --resume для этого запуска будет недоступна."
        )


class FileUploadLock:
    """An ``flock`` on a per-upload lock file, held by an open descriptor.

    The kernel drops the lock when the descriptor closes, including when the
    process dies, so a crashed run never blocks the next one. The file itself
    stays: unlinking it would let a later run lock a fresh file while an
    earlier one still holds the old.
    """

    def __init__(self, fd: int | None) -> None:
        """Own *fd* (``None`` when no lock could be taken)."""
        self._fd = fd

    def release(self) -> None:
        """Close the descriptor, which releases the lock."""
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def lock_upload(project_id: int, fingerprint: str, *, host: str) -> FileUploadLock:
    """Hold one upload exclusively for the rest of this run.

    Raises :class:`UploadInProgressError` while another process holds it.
    Where the platform or filesystem offers no ``flock``, the run goes on
    unlocked with a warning, as uploads did before the lock existed.
    """
    if fcntl is None:
        logger.warning(
            "Блокировка файлов недоступна на этой платформе — одновременный запуск той же загрузки не исключён."
        )
        return FileUploadLock(None)
    path = get_manifest_path(project_id, fingerprint, host=host).with_suffix(".lock")
    try:
        ensure_shared_dir(path.parent)
        fd = _open_lock_file(path)
    except OSError as e:
        raise Cveta2Error(f"Не удалось открыть файл блокировки загрузки {path}: {e}") from e
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(fd)
        raise UploadInProgressError(
            f"Эта загрузка уже выполняется другим процессом (блокировка {path}). "
            "Дождитесь его завершения; при необходимости затем используйте --resume."
        ) from e
    except OSError as e:
        os.close(fd)
        logger.warning(f"Не удалось заблокировать {path} ({e}) — одновременный запуск той же загрузки не исключён.")
        return FileUploadLock(None)
    return FileUploadLock(fd)


def _open_lock_file(path: Path) -> int:
    """Open the lock file, giving a newly created one the shared cache mode."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    except FileExistsError:
        return os.open(path, os.O_RDONLY)
    try:
        os.fchmod(fd, FILE_MODE)
    except OSError as e:
        logger.debug(f"Не удалось выставить права {oct(FILE_MODE)} на {path}: {e}")
    return fd


def load_manifest(project_id: int, fingerprint: str, *, host: str) -> UploadManifest | None:
    """Return the manifest for *fingerprint*, or None when absent or stale."""
    path = get_manifest_path(project_id, fingerprint, host=host)
    manifest = _read_manifest(path)
    if manifest is None:
        return None
    if (
        manifest.host != normalize_upload_host(host)
        or manifest.project_id != project_id
        or manifest.fingerprint != fingerprint
    ):
        logger.warning(f"Состояние загрузки {path} относится к другой загрузке — игнорируем.")
        return None
    return manifest


def list_manifests(project_id: int, *, host: str) -> list[UploadManifest]:
    """Return every readable manifest for *project_id*, newest first."""
    directory = get_upload_manifest_dir(project_id, host=host)
    if not directory.is_dir():
        return []
    found = [load_manifest(project_id, path.stem, host=host) for path in sorted(directory.glob("*.json"))]
    return sorted(
        (m for m in found if m is not None),
        key=lambda m: m.started_at,
        reverse=True,
    )


def delete_manifest(project_id: int, fingerprint: str, *, host: str, task_id: int | None = None) -> None:
    """Drop the manifest once its upload has finished."""
    path = get_manifest_path(project_id, fingerprint, host=host)
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

    path = staticmethod(get_manifest_path)
    lock = staticmethod(lock_upload)
    load = staticmethod(load_manifest)
    save = staticmethod(save_manifest)
    list_for_project = staticmethod(list_manifests)
    delete = staticmethod(delete_manifest)
    new = staticmethod(new_manifest)

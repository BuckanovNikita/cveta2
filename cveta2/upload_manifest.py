"""Crash record of an in-flight upload, so ``--resume`` can pick it up.

The manifest holds *intent and identity*: which task id was created, and
what the run had already decided (the frozen ``YYYY-MM`` folder assignment
and the frame order). In-flight stage decisions come from reading CVAT back:
a lost reply cannot prove what the server applied. After every remote stage
finishes, completed counts mark a successful outcome so failed local cleanup
cannot advertise another upload or replay remote writes.

Layout follows ``task_cache``: a versioned pydantic envelope under an XDG
cache root, written atomically through ``fs_utils.replace_shared_bytes``.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
from loguru import logger
from pydantic import BaseModel, ValidationError

from cveta2.exceptions import Cveta2Error
from cveta2.fs_utils import default_cache_base, replace_shared_bytes
from cveta2.image_downloader import CloudStorageInfo

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

MANIFEST_SCHEMA_VERSION = 3


class UploadManifest(BaseModel):
    """One unfinished upload, keyed by what it was uploading."""

    schema_version: int
    started_at: str
    dataset_path: str
    fingerprint: str
    project_id: int
    host: str
    task_name: str
    cs_info: CloudStorageInfo
    # Frozen because _assign_month_folder reads the clock: a resume that
    # crossed a month boundary would otherwise place the images it still
    # owes into a different folder than the frame order already promised.
    name_to_server_file: dict[str, str]
    task_image_names: list[str]
    task_id: int | None = None
    mapping_identity: str = ""
    intent_complete: bool = False
    creation_pending: bool = False
    completed_counts: tuple[int, int, int] | None = None

    def describe(self) -> str:
        """One line naming what this manifest was uploading, for a mismatch."""
        return (
            f"{self.dataset_path} → задача {self.task_name!r} "
            f"({len(self.task_image_names)} изображений, "
            f"task_id={self.task_id if self.task_id is not None else '—'}, "
            f"начата {self.started_at})"
        )


_BBOX_COLUMNS = ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br")


def validate_upload_boxes(annotations: pd.DataFrame) -> None:
    """Reject incomplete labelled boxes before any upload side effect."""
    if annotations.empty or "instance_label" not in annotations:
        return
    labelled = annotations["instance_label"].notna() & annotations[
        "instance_label"
    ].astype(str).str.strip().ne("")
    if "instance_shape" in annotations:
        labelled &= annotations["instance_shape"].ne("deleted")
    missing = [column for column in _BBOX_COLUMNS if column not in annotations]
    invalid = (
        labelled.copy()
        if missing
        else labelled
        & ~annotations[list(_BBOX_COLUMNS)]
        .apply(pd.to_numeric, errors="coerce")
        .map(lambda value: pd.notna(value) and math.isfinite(float(value)))
        .all(axis=1)
    )
    if invalid.any():
        details = ", ".join(
            f"строка {index!s}, изображение {row.get('image_name', '?')!r}"
            for index, row in annotations.loc[invalid].iterrows()
        )
        raise Cveta2Error(
            f"Неполный или некорректный bbox: {details}. Загрузка не начата."
        )


def compute_fingerprint(  # noqa: PLR0913
    image_names: Iterable[str],
    deleted_names: Iterable[str],
    labels: Sequence[str],
    *,
    annotations: pd.DataFrame | None = None,
    options: dict[str, object] | None = None,
    task_name: str = "",
) -> str:
    """Hash normalized upload intent, preserving authoritative frame order."""
    images = list(image_names)
    intent: dict[str, object] = {
        "images": images if annotations is not None else sorted(images),
        "deleted": sorted(deleted_names),
        "labels": sorted(labels),
        "options": options or {},
        "task_name": task_name,
    }
    if annotations is not None:
        # Local lookup paths are not annotation intent; generated S3 paths
        # are separately frozen and verified against the manifest mapping.
        columns = sorted(
            column
            for column in annotations.columns
            if column not in {"image_path", "s3_uri", "s3_path", "image_url"}
            and annotations[column].notna().any()
        )
        records: list[str] = []
        for row in annotations[columns].to_dict("records"):
            normalized = {
                column: None
                if pd.isna(value)
                else float(value)
                if column in _BBOX_COLUMNS
                else value
                for column, value in row.items()
            }
            records.append(
                json.dumps(
                    normalized,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                    allow_nan=False,
                )
            )
        intent["annotations"] = sorted(records)
    return hashlib.sha256(
        json.dumps(intent, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def normalize_upload_host(host: str) -> str:
    """Canonical server identity, preserving a case-sensitive deployment path."""
    url = urlsplit(host)
    return urlunsplit(
        (url.scheme.lower(), url.netloc.lower(), url.path.rstrip("/"), "", "")
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


def compute_mapping_identity(manifest: UploadManifest) -> str:
    """Bind the frozen storage and ordered server files to recovery state."""
    payload = {
        "storage": manifest.cs_info.model_dump(mode="json"),
        "mapping": manifest.name_to_server_file,
        "frames": manifest.task_image_names,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


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
    manifest = UploadManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        intent_complete=intent_complete,
        started_at=datetime.now(timezone.utc).isoformat(),
        dataset_path=dataset_path,
        fingerprint=fingerprint,
        project_id=project_id,
        host=normalize_upload_host(host),
        task_name=task_name,
        cs_info=cs_info,
        name_to_server_file=name_to_server_file,
        task_image_names=task_image_names,
    )
    manifest.mapping_identity = compute_mapping_identity(manifest)
    return manifest


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

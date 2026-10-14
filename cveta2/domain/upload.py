"""Pure upload intent, manifest schema and recovery identity validation."""

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
from pydantic import BaseModel

from cveta2.domain.errors import Cveta2Error
from cveta2.domain.storage import CloudStorageInfo

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
    started_at: str,
) -> UploadManifest:
    """Build a manifest for an upload that is about to touch CVAT."""
    manifest = UploadManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        intent_complete=intent_complete,
        started_at=started_at,
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

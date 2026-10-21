"""Resolved upload values and application-owned effect dependencies."""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from cveta2.application.ports.cache import CacheInvalidator
from cveta2.application.ports.manifests import ManifestStore
from cveta2.application.ports.storage import UploadStorage
from cveta2.application.ports.workflow_files import UploadFiles
from cveta2.domain.storage import CloudStorageInfo

UPLOAD_REQUIRED_COLUMNS: set[str] = {"image_name", "instance_label"}
"""Columns an upload CSV must carry, shared by CLI and API adapters."""


@dataclass(frozen=True)
class UploadDependencies:
    """Image staging, recovery and invalidation effects for an upload."""

    storage: UploadStorage
    files: UploadFiles
    manifests: ManifestStore
    invalidate: CacheInvalidator


@dataclass(frozen=True)
class UploadPlan:
    """Resolved upload inputs: filtered rows and ordered image-name lists.

    Name lists keep CSV row order (deduped by first occurrence) so the
    created CVAT task shows frames in the same order as the source CSV.
    """

    annotations: pd.DataFrame
    image_names: list[str]
    deleted_names: list[str]


@dataclass(frozen=True)
class UploadOptions:
    """Options for the upload pipeline (all inputs already resolved)."""

    search_dirs: list[Path] = field(default_factory=list)
    segment_size: int = 100
    image_quality: int = 100
    mark_all_deleted: bool = False
    complete: bool = False


@dataclass(frozen=True)
class UploadRequest:
    """Fully-resolved inputs for one upload run."""

    project_id: int
    project_name: str
    task_name: str
    plan: UploadPlan
    options: UploadOptions
    dataset_path: str = ""
    labels: tuple[str, ...] = ()
    resume: bool = False


@dataclass(frozen=True)
class _StagedUpload:
    """Result of the S3 staging step: storage info and enriched rows."""

    cs_info: CloudStorageInfo
    annotations: pd.DataFrame
    task_image_names: list[str]
    name_to_server_file: dict[str, str]


@dataclass(frozen=True)
class UploadOutcome:
    """Summary of a completed upload."""

    task_id: int
    task_name: str
    images: int
    deleted: int
    annotations: int
    issues: int
    jobs: int


# Keep the established qualified identities for serialized request/value objects.
UploadDependencies.__module__ = "cveta2.application.use_cases.upload"
UploadPlan.__module__ = "cveta2.application.use_cases.upload"
UploadOptions.__module__ = "cveta2.application.use_cases.upload"
UploadRequest.__module__ = "cveta2.application.use_cases.upload"
_StagedUpload.__module__ = "cveta2.application.use_cases.upload"
UploadOutcome.__module__ = "cveta2.application.use_cases.upload"

"""Typed dataset bundle, policy and orchestration records."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from cveta2.domain.errors import Cveta2Error
from cveta2.domain.verification.models import ValidationResult


class UploadError(Cveta2Error):
    """An actionable input, configuration or publication failure."""


class UploadCancelled(Cveta2Error):  # noqa: N818 - cancellation contract name.
    """The user declined a required decision or closed interactive input."""


class ApiClass(BaseModel):
    """The class API identity uses number, independently of its internal id."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    id: int
    number: int
    name: str = Field(min_length=1)
    techClass: bool  # noqa: N815 - external registry field.
    isPeriodical: bool  # noqa: N815 - external registry field.
    isCritical: bool  # noqa: N815 - external registry field.
    threshold: float = Field(allow_inf_nan=False)


class ClassInfo(BaseModel):
    """Persisted class identity, exclusion policy and obsolete names."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    prod_id: int
    empty: bool = False
    alt_names: list[str] = Field(default_factory=list)

    @field_validator("alt_names")
    @staticmethod
    def nonempty_aliases(value: list[str]) -> list[str]:
        """Reject empty historical labels."""
        if any(not name for name in value):
            raise ValueError("Class aliases must be nonempty strings")
        return value


class ImageRoots(BaseModel):
    """Independent local directories and S3 prefixes; no implied mirroring."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    local_root: list[str] = Field(default_factory=list)
    s3_root: list[str] = Field(default_factory=list)


class DatasetMetadata(BaseModel):
    """Portable serialized bundle contract, without authentication secrets."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    api_url: str
    classes: dict[str, ClassInfo]
    images: ImageRoots = Field(default_factory=ImageRoots)

    @field_validator("api_url")
    @staticmethod
    def public_http_url(value: str) -> str:
        """Require a public HTTP URL without embedded credentials."""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("api_url must be an HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("api_url must not contain credentials")
        return value

    @field_validator("classes")
    @staticmethod
    def nonempty_class_names(value: dict[str, ClassInfo]) -> dict[str, ClassInfo]:
        """Reject empty canonical class labels."""
        if any(not name for name in value):
            raise ValueError("Class names must be nonempty")
        return value


class TaskManifest(BaseModel):
    """Task IDs supported by the fetch evidence and final clean annotations."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    included: list[int]
    obsolete: list[int]


@dataclass(frozen=True)
class ClassChange:
    """One added identity or canonical name transition."""

    kind: Literal["added", "renamed"]
    prod_id: int
    name: str
    old_name: str | None = None


@dataclass(frozen=True)
class ClassUpdate:
    """Reconciled identities and reviewable registry changes."""

    classes: dict[str, ClassInfo]
    changes: tuple[ClassChange, ...]


@dataclass(frozen=True)
class FetchTables:
    """Original four-table fetch evidence."""

    dataset: pd.DataFrame
    obsolete: pd.DataFrame
    in_progress: pd.DataFrame
    deleted: pd.DataFrame


@dataclass(frozen=True)
class BundleValidation:
    """Training-policy result with original broken-image evidence."""

    result: ValidationResult
    broken_images: pd.DataFrame
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class DatasetParent:
    """Finalized remote lineage and locally downloaded metadata."""

    dataset_id: str
    project: str
    name: str
    version: str | None
    metadata_path: Path | None


@dataclass(frozen=True)
class Publication:
    """Verified finalized child identity."""

    dataset_id: str
    version: str | None


@dataclass(frozen=True)
class UploadRequest:
    """Source and explicit bundle publication choices."""

    source: Path
    project: str
    dataset_name: str | None = None
    api_url: str | None = None
    local_roots: tuple[str, ...] = ()
    s3_roots: tuple[str, ...] = ()
    output_dir: Path | None = None

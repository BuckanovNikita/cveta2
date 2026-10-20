"""Local review decisions and immutable dataset preparation contracts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from cveta2.domain.bundle.models import (
    BundleValidation,
    ClassChange,
    DatasetMetadata,
    DatasetParent,
    FetchTables,
    TaskManifest,
    UploadError,
)

SOURCE_NAMES = ("dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv")
PAYLOAD_NAMES = ("dataset.csv", "dataset.yaml", "tasks.yaml")


class PrepareOptions(BaseModel):
    """Explicit destination and review policy; omitted decisions never prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    project: str
    dataset_name: str | None = None
    api_url: str | None = None
    local_roots: tuple[str, ...] = ()
    s3_roots: tuple[str, ...] = ()
    class_empty: dict[int, bool] = Field(default_factory=dict)
    accept_default_classes: bool = False
    accept_class_changes: bool = False
    clean: bool = False


@dataclass(frozen=True)
class Decision:
    """A missing user choice that an incoming interface may collect."""

    kind: Literal[
        "dataset_name", "api_url", "class_empty", "class_changes", "local_roots"
    ]
    message: str
    choices: tuple[str, ...] = ()
    class_id: int | None = None


class MissingDecisions(UploadError):  # noqa: N818 - structured public decision contract.
    """Required preparation choices are absent; API consumers receive details."""

    def __init__(self, decisions: tuple[Decision, ...]) -> None:
        """Retain actionable choices without starting an interactive session."""
        self.decisions = decisions
        super().__init__("\n".join(decision.message for decision in decisions))


class PreparedRecord(BaseModel):
    """Versioned local binding of reviewed payload, evidence and destination."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    format_version: Literal[1] = 1
    options: PrepareOptions
    parent_id: str | None
    parent_version: str | None
    source_hashes: dict[str, str]
    payload_hashes: dict[str, str]


@dataclass(frozen=True)
class SourceSnapshot:
    """Exact captured source bytes and the tables parsed from those bytes."""

    base_dir: Path
    content: dict[str, bytes]
    tables: FetchTables


@dataclass(frozen=True)
class BundleDraft:
    """Fully evaluated proposal handed to the persistence adapter once."""

    source: SourceSnapshot
    metadata: DatasetMetadata
    tasks: TaskManifest
    validation: BundleValidation
    options: PrepareOptions
    parent: DatasetParent | None
    changes: tuple[ClassChange, ...]
    ready: bool


@dataclass(frozen=True)
class PreparedDataset:
    """A local report and, only when ready, an uploadable reviewed bundle."""

    directory: Path
    ready: bool
    validation: BundleValidation
    metadata: DatasetMetadata
    tasks: TaskManifest


@dataclass(frozen=True)
class StoredBundle:
    """Stable checked publication bytes staged for one upload attempt."""

    directory: Path
    source: SourceSnapshot
    record: PreparedRecord
    metadata: DatasetMetadata
    tasks: TaskManifest
    dataset: pd.DataFrame
    payload: dict[str, bytes]

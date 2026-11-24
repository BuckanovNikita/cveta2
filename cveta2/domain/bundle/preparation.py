"""Preparation decisions, the prepared-bundle layout and the bundle as ``upload-dataset`` reads it."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from cveta2.domain.bundle.models import (
    BundleValidation,
    ClassChange,
    ClassMarkChange,
    DatasetMetadata,
    DatasetParent,
    FetchTables,
    TaskManifest,
    UploadError,
)
from cveta2.domain.managed.models import ClearMLDestination

SOURCE_NAMES = ("dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv")
PAYLOAD_NAMES = ("dataset.csv", "dataset.yaml", "tasks.yaml")
SOURCES_ARCHIVE = "sources.tar.gz"
PUBLISHED_NAMES = (*PAYLOAD_NAMES, SOURCES_ARCHIVE)


class PrepareOptions(BaseModel):
    """Explicit destination and review policy; omitted decisions never prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    project: str
    dataset_name: str | None = None
    api_url: str | None = None
    output_uri: str | None = None
    local_roots: tuple[str, ...] = ()
    s3_roots: tuple[str, ...] = ()
    class_empty: dict[int, bool] = Field(default_factory=dict)
    accept_default_classes: bool = False
    accept_class_changes: bool = False
    clean: bool = False


@dataclass(frozen=True)
class Decision:
    """A missing user choice that an incoming interface may collect."""

    kind: Literal["dataset_name", "api_url", "class_empty", "class_changes", "local_roots"]
    message: str
    choices: tuple[str, ...] = ()
    class_id: int | None = None


class MissingDecisions(UploadError):  # noqa: N818 - structured public decision contract.
    """Required preparation choices are absent; API consumers receive details."""

    def __init__(self, decisions: tuple[Decision, ...]) -> None:
        """Retain actionable choices without starting an interactive session."""
        self.decisions = decisions
        super().__init__("\n".join(decision.message for decision in decisions))


@dataclass(frozen=True)
class SourceSnapshot:
    """Exact captured source bytes and the tables parsed from those bytes."""

    base_dir: Path
    content: dict[str, bytes]
    tables: FetchTables


@dataclass(frozen=True)
class BundleProposal:
    """Fully evaluated preparation handed to the persistence adapter once."""

    source: SourceSnapshot
    metadata: DatasetMetadata
    tasks: TaskManifest
    validation: BundleValidation
    destination: ClearMLDestination
    parent: DatasetParent | None
    changes: tuple[ClassChange, ...]
    blockers: tuple[str, ...]
    pending: tuple[str, ...] = ()
    mark_changes: tuple[ClassMarkChange, ...] = ()
    dropped_local_roots: tuple[str, ...] = ()
    split_prefilled: int = 0

    @property
    def ready(self) -> bool:
        """Whether the payload is written: nothing blocks it."""
        return not self.blockers


@dataclass(frozen=True, kw_only=True)
class PreparedDataset:
    """A local report and, only when ready, the editable payload of the bundle."""

    directory: Path
    ready: bool
    validation: BundleValidation
    metadata: DatasetMetadata
    tasks: TaskManifest
    blockers: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()
    changes: tuple[ClassChange, ...] = ()
    mark_changes: tuple[ClassMarkChange, ...] = ()
    dropped_local_roots: tuple[str, ...] = ()
    split_prefilled: int = 0


@dataclass(frozen=True)
class VerifyRecord:
    """The destination and parent that ``verify`` recorded in ``report.json``."""

    project: str
    dataset: str
    parent_id: str | None
    parent_version: str | None


@dataclass(frozen=True)
class CurrentBundle:
    """A prepared bundle's files as read now; every one of them may have been edited."""

    directory: Path
    source: SourceSnapshot
    metadata: DatasetMetadata
    dataset: pd.DataFrame
    content: dict[str, bytes]
    recorded: VerifyRecord | None
    previous_publication: dict[str, object] | None

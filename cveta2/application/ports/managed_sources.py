"""Typed effects for managed source acquisition and portable snapshots."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta, RawIssue, RawJob
from cveta2.domain.managed.models import ManagedSnapshot, SourceSnapshot, TaskSnapshot
from cveta2.domain.models import AnnotationRecord, DeletedImage, TaskInfo

TaskAssembler = Callable[
    [
        TaskInfo,
        RawDataMeta,
        RawAnnotations,
        dict[int, str],
        dict[int, str],
        list[RawIssue],
        list[RawJob],
    ],
    tuple[list[AnnotationRecord], list[DeletedImage]],
]


@dataclass(frozen=True)
class ProjectState:
    """Live task inventory and project-label identity, without annotations."""

    tasks: list[TaskSnapshot]
    labels_fingerprint: str


@dataclass(frozen=True)
class S3Object:
    """One captured object; ETag is opaque and never used as a content hash."""

    content: bytes
    content_hash: str
    etag: str | None = None
    version_id: str | None = None


class CvatSourceReader(Protocol):
    """Read one project's inventory and only the tasks requiring fresh data."""

    def inspect_project(self, project_id: int) -> ProjectState:
        """Return live task metadata and a stable label fingerprint."""
        ...

    def read_task(self, project_id: int, task: TaskSnapshot) -> TaskSnapshot:
        """Capture all task records/deletions and actual all-job completion."""
        ...


class S3CsvReader(Protocol):
    """Capture the bytes of an exact S3 object without reading images."""

    def read_object(self, uri: str) -> S3Object:
        """Return bytes and object identity, or fail the whole source."""
        ...


class SourceFiles(Protocol):
    """Own CSV parsing, source-local partition serialization and persistence."""

    def project_tables(self, tasks: list[TaskSnapshot]) -> dict[str, str]:
        """Rebuild all four project partitions from original per-task rows."""
        ...

    def csv_tables(self, content: bytes, source: str) -> dict[str, str]:
        """Validate an annotation CSV and preserve its original lexical cells."""
        ...

    def source_frame(self, snapshot: SourceSnapshot) -> pd.DataFrame:
        """Parse retained source rows and attach unambiguous provenance."""
        ...

    def read_snapshot(self, path: Path) -> ManagedSnapshot:
        """Read a strict local source snapshot."""
        ...

    def export(
        self, directory: Path, snapshot: ManagedSnapshot, frame: pd.DataFrame
    ) -> None:
        """Write a complete candidate into a fresh destination directory."""
        ...


class PublishedSources(Protocol):
    """Read published task/source evidence by immutable dataset identity."""

    def read_snapshot(self, dataset_id: str) -> ManagedSnapshot | None:
        """Return managed evidence or None for a legacy three-file dataset."""
        ...

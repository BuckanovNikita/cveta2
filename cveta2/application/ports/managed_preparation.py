"""Typed capture, serialization and media effects for managed preparation."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd
from pydantic import JsonValue

from cveta2.domain.bundle.models import (
    BundleValidation,
    DatasetMetadata,
    FetchTables,
    TaskManifest,
)
from cveta2.domain.managed.models import ManagedSnapshot
from cveta2.domain.managed.preparation import FeedbackFinding, ManagedRecord


@dataclass(frozen=True)
class CapturedManagedInput:
    """Exact input bytes and parsed source evidence captured once."""

    frame: pd.DataFrame
    input_content: bytes
    source_content: bytes
    snapshot: ManagedSnapshot
    source_tables: dict[str, FetchTables]
    origins: frozenset[tuple[str, int, int, int]]
    source_directory: Path


@dataclass(frozen=True)
class ImageHashes:
    """Split identities include placeholders; readable hashes bind real files."""

    identities: dict[str, str]
    readable: dict[str, str]


@dataclass(frozen=True)
class LoadedManagedPreparation:
    """A preparation directory as it is now: no checksum binds its files.

    ``frame`` and ``metadata`` are ``None`` when prepare was blocked and wrote no payload.
    ``ledger_key`` is the SHA-256 of ``source-snapshot.yaml``; it names the shared feedback ledger.
    """

    directory: Path
    record: ManagedRecord
    captured: CapturedManagedInput
    frame: pd.DataFrame | None
    metadata: DatasetMetadata | None
    report: dict[str, JsonValue]
    ledger_key: str


class ManagedPreparationFiles(Protocol):
    """Own local capture, source attestation, image hashes and persistence."""

    def capture(self, transformed: Path, source: Path) -> CapturedManagedInput:
        """Capture transformed input and source snapshot, verifying source tables."""
        ...

    def image_hashes(self, frame: pd.DataFrame) -> ImageHashes:
        """Hash readable local files and assign placeholders to unreadable paths."""
        ...

    def check_roots(self, frame: pd.DataFrame, metadata: DatasetMetadata) -> None:
        """Validate configured roots and transformed source path coverage."""
        ...

    def payload_bytes(self, frame: pd.DataFrame, metadata: DatasetMetadata, tasks: TaskManifest) -> dict[str, bytes]:
        """Serialize the exact three-file publication payload."""
        ...

    def validation_report(  # noqa: PLR0913 - report boundary.
        self,
        validation: BundleValidation,
        *,
        ready: bool,
        findings: list[FeedbackFinding],
        unmapped: int,
        split_replacements: int,
        pending: Sequence[str] = (),
        missing_classes: Sequence[str] = (),
        collisions: Sequence[str] = (),
    ) -> dict[str, JsonValue]:
        """Return JSON-safe diagnostics without inventing successful checks."""
        ...

    def persist(  # noqa: PLR0913, PLR0917 - persistence boundary.
        self,
        directory: Path,
        captured: CapturedManagedInput,
        record: ManagedRecord,
        payload: Mapping[str, bytes],
        report: dict[str, JsonValue],
        broken_images: pd.DataFrame,
    ) -> None:
        """Write a fresh local directory with ``preparation.json`` last."""
        ...

    def load_prepared(self, directory: Path) -> LoadedManagedPreparation:
        """Read and strictly parse the current files; reject symlinks and an unsupported record."""
        ...

    def stage_payload(self, directory: Path) -> AbstractContextManager[Path]:
        """Copy the three payload files into a private temporary directory."""
        ...

    def read_metadata(self, path: Path) -> DatasetMetadata:
        """Parse one ``dataset.yaml`` strictly; errors name fields, never their values."""
        ...

    def read_rows(self, path: Path) -> pd.DataFrame:
        """Read one ``dataset.csv`` without lexical inference."""
        ...

    def write_bookkeeping(self, directory: Path, metadata: DatasetMetadata, tasks: TaskManifest) -> None:
        """Replace only ``dataset.yaml`` and ``tasks.yaml`` of *directory*, each with one rename."""
        ...

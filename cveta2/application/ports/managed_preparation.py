"""Typed capture, serialization and media effects for managed preparation."""

from collections.abc import Mapping
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


@dataclass(frozen=True)
class ImageHashes:
    """Split identities include placeholders; readable hashes bind real files."""

    identities: dict[str, str]
    readable: dict[str, str]


@dataclass(frozen=True)
class LoadedManagedPreparation:
    """Checked immutable publication bytes and their local review binding."""

    directory: Path
    record: ManagedRecord
    frame: pd.DataFrame
    metadata: DatasetMetadata | None
    tasks: TaskManifest | None
    payload: dict[str, bytes]
    input_content: bytes
    source_content: bytes
    report: dict[str, JsonValue]


class ManagedPreparationFiles(Protocol):
    """Own local capture, source attestation, hashes and immutable persistence."""

    def capture(self, transformed: Path, source: Path) -> CapturedManagedInput:
        """Capture transformed input and source snapshot, verifying source tables."""
        ...

    def image_hashes(self, frame: pd.DataFrame) -> ImageHashes:
        """Hash readable local files and assign placeholders to unreadable paths."""
        ...

    def check_roots(self, frame: pd.DataFrame, metadata: DatasetMetadata) -> None:
        """Validate configured roots and transformed source path coverage."""
        ...

    def payload_bytes(
        self, frame: pd.DataFrame, metadata: DatasetMetadata, tasks: TaskManifest
    ) -> dict[str, bytes]:
        """Serialize the exact three-file publication payload."""
        ...

    def validation_report(
        self,
        validation: BundleValidation,
        *,
        ready: bool,
        findings: list[FeedbackFinding],
        unmapped: int,
        split_replacements: int,
    ) -> dict[str, JsonValue]:
        """Return JSON-safe diagnostics without inventing successful checks."""
        ...

    def persist(  # noqa: PLR0913, PLR0917 - immutable persistence boundary.
        self,
        directory: Path,
        captured: CapturedManagedInput,
        record: ManagedRecord,
        payload: Mapping[str, bytes],
        report: dict[str, JsonValue],
        broken_images: pd.DataFrame,
    ) -> None:
        """Write a fresh local directory with completion marker last."""
        ...

    def load_prepared(self, directory: Path) -> LoadedManagedPreparation:
        """Verify record/input/source/payload hashes and reject symlink inputs."""
        ...

    def stage_payload(
        self, payload: Mapping[str, bytes]
    ) -> AbstractContextManager[Path]:
        """Hold a stable private copy until the publication attempt completes."""
        ...

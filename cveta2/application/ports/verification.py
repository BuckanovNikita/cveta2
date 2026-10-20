"""Typed external inspection dependency for dataset validation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from cveta2.domain.verification.models import (
    MediaInspection,
    Profile,
    ValidationOptions,
    ValidationResult,
)


class MediaInspector(Protocol):
    """Supply immutable media and path evidence without policy decisions."""

    def inspect(
        self, frame: pd.DataFrame, *, profile: Profile, options: ValidationOptions
    ) -> MediaInspection:
        """Inspect positional rows using explicit options."""
        ...


@dataclass(frozen=True)
class LoadedVerification:
    """Captured CSV rows and adapter-resolved local path context."""

    frame: pd.DataFrame
    source: Path
    options: ValidationOptions


class VerificationFiles(Protocol):
    """Capture CSV context, persist diagnostics and render optional warnings."""

    def load(self, path: str | Path, options: ValidationOptions) -> LoadedVerification:
        """Read literal cells and resolve the base directory for local media."""
        ...

    def persist(
        self,
        result: ValidationResult,
        directory: str | Path,
        *,
        cleanup: bool,
        input_path: Path,
    ) -> None:
        """Create a new report directory, translating filesystem failures."""
        ...

    def warn(self, result: ValidationResult) -> None:
        """Render optional diagnostics at the outgoing boundary."""
        ...


@dataclass(frozen=True)
class VerificationRequest:
    """Explicit CSV verification and optional report choices."""

    path: str | Path
    profile: Profile = "cveta2"
    options: ValidationOptions | None = None
    output_dir: str | Path | None = None
    cleanup: bool = False

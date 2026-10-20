"""Public configuration, diagnostics and result contracts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from cveta2.domain.errors import Cveta2Error

Profile = Literal["cveta2", "clearml-yolo"]


class ValidationOptions(BaseModel):
    """Validation policy; unknown options are errors rather than silent typos."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    iou_threshold: float = Field(default=0.99, gt=0, le=1, allow_inf_nan=False)
    check_images: bool = False
    image_root: Path | None = None
    base_dir: Path | None = None
    emit_warnings: bool = True


class Issue(BaseModel):
    """A finding referencing zero-based input positions, never index labels."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    row_position: int | None = None
    columns: tuple[str, ...] = ()
    related_rows: tuple[int, ...] = ()
    iou: float | None = None


class DatasetWarning(UserWarning):
    """Recoverable dataset problems and checks requiring caller attention."""


class DatasetInputError(Cveta2Error, ValueError):
    """The input could not be read as an unambiguous CSV table."""


@dataclass(frozen=True)
class MediaRowFact:
    """Immutable local inspection evidence for one original positional row."""

    row_position: int
    canonical_path: str | None = None
    size: tuple[int, int] | None = None
    image_format: str | None = None
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class MediaInspection:
    """External facts consumed without filesystem access by pure policies."""

    rows: tuple[MediaRowFact, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    """Proposed clean rows, original broken rows and positional diagnostics."""

    profile: Profile
    clean: pd.DataFrame
    broken: pd.DataFrame
    clean_row_positions: tuple[int, ...]
    broken_row_positions: tuple[int, ...]
    issues: tuple[Issue, ...]
    input_row_count: int
    checked_checks: tuple[str, ...] = ()
    skipped_checks: tuple[str, ...] = ()
    structural_errors: bool = False
    input_image_count: int = 0
    clean_image_count: int = 0

    @property
    def is_valid(self) -> bool:
        """Whether the original input had no rejection or structural error."""
        return not self.structural_errors and not self.broken_row_positions

    @property
    def requires_cleanup(self) -> bool:
        """Whether rejected records or proposed repairs require explicit acceptance."""
        return bool(self.broken_row_positions) or any(
            issue.code in {"bbox_clipped", "class_canonicalized"}
            for issue in self.issues
        )

    @property
    def warnings(self) -> tuple[Issue, ...]:
        """Non-rejecting findings; rejection reasons remain in ``issues``."""
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def reasons_for(self, row_position: int) -> tuple[Issue, ...]:
        """Return every finding tied to one original input position."""
        return tuple(
            issue
            for issue in self.issues
            if issue.row_position == row_position
            or (
                self.structural_errors
                and issue.row_position is None
                and issue.severity == "error"
                and 0 <= row_position < self.input_row_count
            )
        )

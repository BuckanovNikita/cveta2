"""Construct local verification dependencies and render optional warnings."""

from pathlib import Path

import pandas as pd

from cveta2.adapters.files.media import LocalMediaInspector
from cveta2.adapters.files.verification import (
    LocalVerificationFiles,
    emit_result_warnings,
)
from cveta2.application.ports.verification import VerificationRequest
from cveta2.application.use_cases.verify import verify as run_csv_verification
from cveta2.application.use_cases.verify import verify_dataframe as run_verification
from cveta2.domain.verification.models import (
    DatasetInputError,
    DatasetWarning,
    Issue,
    Profile,
    ValidationOptions,
    ValidationResult,
)
from cveta2.domain.verification.schema import schema_for

__all__ = [
    "DatasetInputError",
    "DatasetWarning",
    "Issue",
    "ValidationOptions",
    "ValidationResult",
    "schema_for",
    "validate_csv",
    "validate_dataframe",
    "verify",
    "verify_dataframe",
]


def verify_dataframe(
    frame: pd.DataFrame,
    *,
    profile: Profile = "cveta2",
    options: ValidationOptions | None = None,
) -> ValidationResult:
    """Validate a DataFrame using local evidence and optional diagnostic warnings."""
    selected = options or ValidationOptions()
    result = run_verification(
        frame, inspector=LocalMediaInspector(), profile=profile, options=selected
    )
    if selected.emit_warnings:
        emit_result_warnings(result)
    return result


def verify(
    path: str | Path,
    *,
    profile: Profile = "cveta2",
    options: ValidationOptions | None = None,
    output_dir: str | Path | None = None,
    cleanup: bool = False,
) -> ValidationResult:
    """Read literal CSV cells and optionally write diagnostics into a new directory."""
    return run_csv_verification(
        VerificationRequest(path, profile, options, output_dir, cleanup),
        files=LocalVerificationFiles(),
        inspector=LocalMediaInspector(),
    )


validate_dataframe = verify_dataframe
validate_csv = verify

"""Prompt-free verification orchestration over explicit inspection ports."""

import pandas as pd

from cveta2.application.ports.verification import (
    MediaInspector,
    VerificationFiles,
    VerificationRequest,
)
from cveta2.domain.verification.models import (
    DatasetInputError,
    Profile,
    ValidationOptions,
    ValidationResult,
)
from cveta2.domain.verification.validation import validate_dataframe


def verify_dataframe(
    frame: pd.DataFrame,
    *,
    inspector: MediaInspector,
    profile: Profile = "cveta2",
    options: ValidationOptions | None = None,
) -> ValidationResult:
    """Inspect local evidence then evaluate the unchanged input table."""
    selected = options or ValidationOptions()
    inspection = inspector.inspect(frame, profile=profile, options=selected)
    return validate_dataframe(
        frame, profile=profile, options=selected, inspection=inspection
    )


def verify(
    request: VerificationRequest,
    *,
    files: VerificationFiles,
    inspector: MediaInspector,
) -> ValidationResult:
    """Verify captured CSV input and explicitly persist requested cleanup."""
    if request.cleanup and request.output_dir is None:
        raise DatasetInputError("Explicit cleanup requires an output destination.")
    selected = request.options or ValidationOptions()
    loaded = files.load(request.path, selected)
    result = verify_dataframe(
        loaded.frame,
        inspector=inspector,
        profile=request.profile,
        options=loaded.options,
    )
    if request.output_dir is not None:
        files.persist(
            result,
            request.output_dir,
            cleanup=request.cleanup,
            input_path=loaded.source,
        )
    if selected.emit_warnings:
        files.warn(result)
    return result

"""Prompt-free public verification and explicit ClearML dataset workflows."""

from pathlib import Path

import pandas as pd

from cveta2.composition.dataset_bundle import (
    prepare_dataset as prepare_bundle,
)
from cveta2.composition.dataset_bundle import (
    upload_dataset as publish_bundle,
)
from cveta2.composition.verification import (
    verify as verify_csv,
)
from cveta2.composition.verification import (
    verify_dataframe as verify_frame,
)
from cveta2.domain.bundle.models import Publication
from cveta2.domain.bundle.preparation import (
    MissingDecisions,
    PreparedDataset,
    PrepareOptions,
)
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
    "MissingDecisions",
    "PrepareOptions",
    "PreparedDataset",
    "Profile",
    "Publication",
    "ValidationOptions",
    "ValidationResult",
    "prepare_dataset",
    "schema_for",
    "upload_dataset",
    "verify",
    "verify_dataframe",
]


def verify(
    path: str | Path,
    *,
    profile: Profile = "cveta2",
    options: ValidationOptions | None = None,
    output_dir: str | Path | None = None,
    clean: bool = False,
) -> ValidationResult:
    """Inspect a CSV; export corrected rows only when clean is explicitly true."""
    return verify_csv(
        path, profile=profile, options=options, output_dir=output_dir, cleanup=clean
    )


def verify_dataframe(
    frame: pd.DataFrame,
    *,
    profile: Profile = "cveta2",
    options: ValidationOptions | None = None,
) -> ValidationResult:
    """Return diagnostics and proposed clean rows without changing the input."""
    return verify_frame(frame, profile=profile, options=options)


def prepare_dataset(
    source: str | Path, *, output_dir: str | Path, options: PrepareOptions
) -> PreparedDataset:
    """Prepare local evidence; missing choices raise structured MissingDecisions."""
    return prepare_bundle(Path(source), Path(output_dir), options)


def upload_dataset(prepared_dir: str | Path) -> Publication:
    """Revalidate a reviewed bundle and finalize exactly its three payload files."""
    return publish_bundle(Path(prepared_dir))

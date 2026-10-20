"""Strict CSV decoding without pandas inference or silent row repair."""

import csv
import io
import json
import os
import warnings
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd

from cveta2.application.ports.verification import LoadedVerification
from cveta2.domain.verification.models import (
    DatasetInputError,
    DatasetWarning,
    Issue,
    ValidationOptions,
    ValidationResult,
)


def read_csv_bytes(content: bytes, *, source: str = "<memory>") -> pd.DataFrame:
    """Parse one captured byte snapshot without lexical inference."""
    try:
        reader = csv.reader(
            io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True
        )
        header = next(reader, None)
        if (
            not header
            or any(not value for value in header)
            or len(header) != len(set(header))
        ):
            raise DatasetInputError("CSV must have unique, nonempty column names.")
        rows: list[list[str]] = []
        for record, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise DatasetInputError(
                    f"CSV record {record} has {len(row)} cells; expected {len(header)}."
                )
            rows.append(row)
    except (UnicodeError, csv.Error) as error:
        raise DatasetInputError(f"Cannot read CSV {source}: {error}") from error
    return pd.DataFrame(rows, columns=header, dtype=object)


def read_csv(path: str | Path) -> pd.DataFrame:
    """Read an unambiguous UTF-8 table preserving literal cells and column order."""
    source = Path(path)
    try:
        return read_csv_bytes(source.read_bytes(), source=str(source))
    except OSError as error:
        raise DatasetInputError(f"Cannot read CSV {source}: {error}") from error


def _metadata_names(columns: list[str]) -> dict[str, str]:
    used = set(columns)
    names = {}
    for key in ("row_position", "reason_codes", "reasons"):
        candidate = f"__validator_{key}"
        while candidate in used:
            candidate += "_"
        names[key] = candidate
        used.add(candidate)
    return names


def report_dict(result: ValidationResult) -> dict[str, Any]:
    """Return JSON-ready diagnostics including proposed coordinate repairs."""
    return {
        "profile": result.profile,
        "is_valid": result.is_valid,
        "requires_cleanup": result.requires_cleanup,
        "structural_errors": result.structural_errors,
        "counts": {
            "input_rows": result.input_row_count,
            "clean_rows": len(result.clean),
            "broken_rows": len(result.broken),
            "input_images": result.input_image_count,
            "clean_images": result.clean_image_count,
        },
        "clean_row_positions": result.clean_row_positions,
        "broken_row_positions": result.broken_row_positions,
        "checked_checks": result.checked_checks,
        "skipped_checks": result.skipped_checks,
        "issues": [issue.model_dump(mode="json") for issue in result.issues],
        "metadata_columns": _metadata_names(list(result.broken.columns)),
    }


def write_report(
    result: ValidationResult,
    directory: str | Path,
    *,
    cleanup: bool = False,
    input_path: Path | None = None,
) -> None:
    """Write diagnostics and explicitly requested clean output in a new directory."""
    destination = Path(directory)
    names = (
        ("broken.csv", "report.json", "clean.csv")
        if cleanup
        else ("broken.csv", "report.json")
    )
    if cleanup and result.structural_errors:
        raise DatasetInputError("Structural errors cannot be cleaned away.")
    targets = [destination / name for name in names]
    if input_path is not None and destination.resolve() == input_path.resolve().parent:
        raise DatasetInputError(
            "Reports require a new directory separate from the input."
        )
    destination.mkdir(parents=True, exist_ok=False)
    report = report_dict(result)
    metadata = _metadata_names(list(result.broken.columns))
    by_row: dict[int, list[Issue]] = defaultdict(list)
    for issue in result.issues:
        if issue.row_position is not None:
            by_row[issue.row_position].append(issue)
    structural_issues = (
        [
            issue
            for issue in result.issues
            if issue.row_position is None and issue.severity == "error"
        ]
        if result.structural_errors
        else []
    )
    broken = result.broken.copy()
    broken[metadata["row_position"]] = list(result.broken_row_positions)
    broken[metadata["reason_codes"]] = [
        json.dumps(
            [issue.code for issue in (*by_row[position], *structural_issues)],
            ensure_ascii=False,
        )
        for position in result.broken_row_positions
    ]
    broken[metadata["reasons"]] = [
        json.dumps(
            [issue.message for issue in (*by_row[position], *structural_issues)],
            ensure_ascii=False,
        )
        for position in result.broken_row_positions
    ]
    # Finish serialization before touching final paths; failed writes cannot
    # truncate old files.
    with TemporaryDirectory(prefix=".csv-validator-", dir=destination) as temporary:
        staging = Path(temporary)
        result.clean.to_csv(staging / "clean.csv", index=False, encoding="utf-8")
        broken.to_csv(staging / "broken.csv", index=False, encoding="utf-8")
        (staging / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for target in targets:
            os.link(staging / target.name, target)


def emit_result_warnings(result: ValidationResult) -> None:
    """Render optional recoverable findings at the outgoing boundary."""
    for code in dict.fromkeys(issue.code for issue in result.warnings):
        message = next(issue.message for issue in result.warnings if issue.code == code)
        warnings.warn(message, DatasetWarning, stacklevel=2)
    if not result.is_valid:
        warnings.warn(
            (
                f"Validation rejected {len(result.broken)} "
                f"of {result.input_row_count} row(s); inspect "
                f"result.issues and result.broken."
            ),
            DatasetWarning,
            stacklevel=2,
        )


class LocalVerificationFiles:
    """Own CSV context resolution and verification report effects."""

    def load(self, path: str | Path, options: ValidationOptions) -> LoadedVerification:
        """Capture lexical rows and derive their base directory at the boundary."""
        source = Path(path)
        try:
            base_dir = options.base_dir or source.absolute().parent
            effective = options.model_copy(update={"base_dir": base_dir})
            frame = read_csv(source)
        except (OSError, RuntimeError, ValueError) as error:
            raise DatasetInputError(
                f"Cannot load verification input {source}: {error}"
            ) from error
        return LoadedVerification(frame, source, effective)

    def persist(
        self,
        result: ValidationResult,
        directory: str | Path,
        *,
        cleanup: bool,
        input_path: Path,
    ) -> None:
        """Write only a new destination and translate filesystem failures."""
        try:
            write_report(result, directory, cleanup=cleanup, input_path=input_path)
        except (OSError, RuntimeError, ValueError) as error:
            raise DatasetInputError(
                f"Cannot write verification output: {error}"
            ) from error

    def warn(self, result: ValidationResult) -> None:
        """Render optional dataset warnings."""
        emit_result_warnings(result)

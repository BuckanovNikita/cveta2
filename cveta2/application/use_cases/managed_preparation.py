"""Prepare opaque transformed records while retaining original managed evidence."""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

import pandas as pd

from cveta2.application.ports.managed_preparation import (
    CapturedManagedInput,
    ManagedPreparationFiles,
)
from cveta2.application.ports.verification import MediaInspector
from cveta2.domain.bundle.models import DatasetMetadata, TaskManifest
from cveta2.domain.bundle.tasks import derive_tasks
from cveta2.domain.bundle.validation import validate_bundle
from cveta2.domain.managed.models import (
    ManagedError,
    ManagedMetadata,
    ProjectConfig,
    definition_fingerprint,
)
from cveta2.domain.managed.policies import assign_splits, resolve_overlaps
from cveta2.domain.managed.preparation import (
    FeedbackFinding,
    ManagedRecord,
    PreparationSummary,
)
from cveta2.domain.verification.models import ValidationOptions, ValidationResult


def _integer(value: object) -> int | None:
    """Interpret explicit CSV identity without guessing invalid source values."""
    try:
        number = Decimal(str(value))
        return (
            int(number)
            if number.is_finite()
            and number >= 0
            and number == number.to_integral_value()
            else None
        )
    except InvalidOperation:
        return None


def _origin(
    row: dict[str, object], captured: CapturedManagedInput
) -> tuple[str, int, int, int] | None:
    """Attest an explicit source reference against original per-task frame rows."""
    source_id = row.get("source_id")
    if not isinstance(source_id, str):
        return None
    source = next(
        (source for source in captured.snapshot.sources if source.name == source_id),
        None,
    )
    if source is None or source.type != "cvat" or source.project_id is None:
        return None
    task_id, frame_id = (
        _integer(row.get("source_task_id")),
        _integer(row.get("source_frame_id")),
    )
    if task_id is None or frame_id is None:
        return None
    project = row.get("source_project_id")
    if project not in (None, "") and _integer(project) != source.project_id:
        return None
    origin = (source_id, source.project_id, task_id, frame_id)
    return origin if origin in captured.origins else None


def _feedback(
    frame: pd.DataFrame, validation: ValidationResult, captured: CapturedManagedInput
) -> tuple[list[FeedbackFinding], int]:
    """Group rejected-row reasons under only independently attested CVAT frames."""
    reasons: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for issue in validation.issues:
        if issue.severity == "error" and issue.row_position is not None:
            reasons[issue.row_position].append((issue.code, issue.message))
    grouped: dict[tuple[str, int, int, int], set[tuple[str, str]]] = defaultdict(set)
    unmapped = 0
    for position, findings in sorted(reasons.items()):
        row = cast("dict[str, object]", frame.iloc[position].to_dict())
        origin = _origin(row, captured)
        if origin is None:
            unmapped += 1
        else:
            grouped[origin].update(findings)
    result = []
    for origin, frame_findings in sorted(grouped.items()):
        codes = sorted({code for code, _message in frame_findings})
        marker = hashlib.sha256(
            json.dumps([*origin, codes], ensure_ascii=False).encode()
        ).hexdigest()
        result.append(
            FeedbackFinding(
                source_id=origin[0],
                project_id=origin[1],
                task_id=origin[2],
                frame_id=origin[3],
                codes=codes,
                messages=sorted({message for _code, message in frame_findings}),
                marker=f"cveta2:verification:{marker}",
            )
        )
    return result, unmapped


def _tasks(clean: pd.DataFrame, captured: CapturedManagedInput) -> TaskManifest:
    """Derive obsolete evidence per source; include only attested CVAT origins."""
    included = {
        origin[2]
        for row in clean.to_dict(orient="records")
        if (origin := _origin(cast("dict[str, object]", row), captured)) is not None
    }
    obsolete: set[int] = set()
    for source in captured.snapshot.sources:
        if source.type == "cvat":
            tables = captured.source_tables[source.name]
            obsolete.update(derive_tasks(tables, tables.dataset.iloc[0:0]).obsolete)
    return TaskManifest(included=sorted(included), obsolete=sorted(obsolete - included))


def prepare_managed(  # noqa: PLR0913, PLR0917 - explicit workflow boundary.
    config: ProjectConfig,
    name: str,
    transformed: Path,
    source: Path,
    directory: Path,
    metadata: DatasetMetadata,
    *,
    registry_hash: str,
    files: ManagedPreparationFiles,
    media: MediaInspector,
    parent_id: str | None = None,
    parent_version: str | None = None,
    parent_metadata: DatasetMetadata | None = None,
    clean: bool = False,
) -> PreparationSummary:
    """Split, validate and persist a fresh preparation without remote mutation."""
    definition_hash = definition_fingerprint(config, name)
    definition = config.datasets[name]
    captured = files.capture(transformed, source)
    snapshot = captured.snapshot
    if snapshot.definition_hash != definition_hash:
        raise ManagedError("Source definition changed; fetch the managed dataset again")
    if snapshot.registry_hash != registry_hash:
        raise ManagedError("Class registry changed; fetch the managed dataset again")
    if snapshot.parent_id != parent_id:
        raise ManagedError("Source parent changed; fetch the managed dataset again")
    previous = dict(snapshot.assignments)
    if parent_metadata is not None and parent_metadata.managed is not None:
        if parent_metadata.managed.definition.splits != definition.splits:
            raise ManagedError("Split policy changed; choose a new dataset lineage")
        previous.update(parent_metadata.managed.assignments)
    files.check_roots(captured.frame, metadata)
    image_hashes = files.image_hashes(captured.frame)
    frame = resolve_overlaps(
        captured.frame, image_hashes.identities, definition.overlaps
    )
    split_frame, assignments = assign_splits(
        frame, definition.splits, image_hashes.identities, previous
    )
    replacements = (
        int((frame["split"] != split_frame["split"]).sum()) if "split" in frame else 0
    )
    inspection = media.inspect(
        split_frame,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
    )
    validation = validate_bundle(split_frame, metadata, inspection=inspection)
    ready = (
        not validation.blockers
        and not validation.result.structural_errors
        and (clean or not validation.result.requires_cleanup)
    )
    findings, unmapped = _feedback(split_frame, validation.result, captured)
    tasks = _tasks(validation.result.clean, captured)
    actual_hashes = {
        path: image_hashes.readable[path]
        for path in set(validation.result.clean.get("image_path", []))
        if path in image_hashes.readable
    }
    accepted_assignments = {
        digest: value
        for digest, value in assignments.items()
        if not digest.startswith("unreadable:")
    }
    prepared_snapshot = snapshot.model_copy(
        update={"assignments": accepted_assignments, "image_hashes": actual_hashes}
    )
    prepared_metadata = metadata.model_copy(
        update={
            "managed": ManagedMetadata(
                name=name,
                definition_hash=definition_hash,
                definition=definition,
                cvat=config.cvat,
                assignments=accepted_assignments,
            )
        }
    )
    tasks = tasks.model_copy(update={"managed": prepared_snapshot})
    payload = (
        files.payload_bytes(validation.result.clean, prepared_metadata, tasks)
        if ready
        else {}
    )
    record = ManagedRecord(
        name=name,
        definition_hash=definition_hash,
        parent_id=parent_id,
        parent_version=parent_version,
        registry_hash=registry_hash,
        source_hash=hashlib.sha256(captured.source_content).hexdigest(),
        input_hash=hashlib.sha256(captured.input_content).hexdigest(),
        payload_hashes={
            key: hashlib.sha256(value).hexdigest() for key, value in payload.items()
        },
        image_hashes=actual_hashes,
        snapshot=prepared_snapshot,
        findings=findings,
        ready=ready,
        clean=clean,
    )
    report = files.validation_report(
        validation,
        ready=ready,
        findings=findings,
        unmapped=unmapped,
        split_replacements=replacements,
    )
    files.persist(
        directory, captured, record, payload, report, validation.broken_images
    )
    return PreparationSummary(directory=directory, ready=ready, report=report)

"""Prepare opaque transformed records while retaining original managed evidence."""

import dataclasses
import hashlib
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

import pandas as pd
from loguru import logger

from cveta2.application.ports.dataset_bundle import S3Storage
from cveta2.application.ports.managed_preparation import (
    CapturedManagedInput,
    ManagedPreparationFiles,
)
from cveta2.application.ports.verification import MediaInspector
from cveta2.application.use_cases.dataset_bundle import split_pending
from cveta2.domain.bundle.models import DatasetMetadata, TaskManifest
from cveta2.domain.bundle.tasks import derive_tasks
from cveta2.domain.bundle.validation import missing_active_classes, validate_bundle
from cveta2.domain.managed.evidence import require_complete_evidence, source_differences
from cveta2.domain.managed.models import (
    ManagedError,
    ManagedMetadata,
    ProjectConfig,
    dataset_definition,
    definition_fingerprint,
)
from cveta2.domain.managed.policies import (
    SplitName,
    propagate_splits,
    rebuild_assignments,
    resolve_overlaps,
    split_collisions,
)
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
        return int(number) if number.is_finite() and number >= 0 and number == number.to_integral_value() else None
    except InvalidOperation:
        return None


def _origin(row: dict[str, object], captured: CapturedManagedInput) -> tuple[str, int, int, int] | None:
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


# A split mistake is the CSV author's to fix; it never becomes feedback on an annotator's frame.
_SPLIT_CODES = frozenset({"invalid_split", "split_conflict"})


def _feedback(
    frame: pd.DataFrame, validation: ValidationResult, captured: CapturedManagedInput
) -> tuple[list[FeedbackFinding], int]:
    """Group rejected-row reasons under only independently attested CVAT frames.

    A quarantine counts only when some row that triggered it has a reason other than a split mistake.
    """
    errors = [issue for issue in validation.issues if issue.severity == "error" and issue.row_position is not None]
    direct: dict[int, set[str]] = defaultdict(set)
    for issue in errors:
        if issue.code != "image_quarantined":
            direct[cast("int", issue.row_position)].add(issue.code)
    reasons: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for issue in errors:
        if issue.code in _SPLIT_CODES or (
            issue.code == "image_quarantined" and all(direct[row] <= _SPLIT_CODES for row in issue.related_rows)
        ):
            continue
        reasons[cast("int", issue.row_position)].append((issue.code, issue.message))
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
        marker = hashlib.sha256(json.dumps([*origin, codes], ensure_ascii=False).encode()).hexdigest()
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


def published_assignments(parent_metadata: DatasetMetadata | None) -> dict[str, SplitName]:
    """Return the published splits a managed parent records, by content identity.

    No parent means none; a parent without a ``managed`` block is refused.
    """
    if parent_metadata is None:
        return {}
    if parent_metadata.managed is None:
        raise ManagedError("Parent is not a managed dataset version")
    return dict(parent_metadata.managed.assignments)


def check_parent(parent_id: str | None, parent_metadata: DatasetMetadata | None, *, first: bool) -> None:
    """Require a managed parent, or no managed version when a lineage is started with ``first``.

    *parent_metadata* is the latest version's ``dataset.yaml`` (``None`` when it has none).
    """
    if parent_id is None:
        return
    managed = parent_metadata is not None and parent_metadata.managed is not None
    if first and managed:
        raise ManagedError(f"Managed lineage already exists at parent {parent_id}; prepare without --first")
    if not first and not managed:
        raise ManagedError(
            f"Parent {parent_id} is not a managed dataset version; start a managed lineage with dataset prepare --first"
        )


def prepare_managed(  # noqa: PLR0913, PLR0917 - explicit workflow boundary.
    config: ProjectConfig,
    name: str,
    transformed: Path,
    source: Path,
    directory: Path,
    metadata: DatasetMetadata,
    *,
    files: ManagedPreparationFiles,
    media: MediaInspector,
    s3_roots: S3Storage,
    parent_id: str | None = None,
    parent_version: str | None = None,
    parent_metadata: DatasetMetadata | None = None,
    clean: bool = False,
    first: bool = False,
) -> PreparationSummary:
    """Propagate published splits, validate and persist a fresh preparation without remote mutation.

    *parent_id* is the latest finalized version. With *first* it must not be managed and
    nothing is read from it: every split comes from the transformed CSV. An empty split is
    pending, not a blocker; the payload is written only when nothing blocks it.
    """
    check_parent(parent_id, parent_metadata, first=first)
    definition = dataset_definition(config, name)
    definition_hash = definition_fingerprint(config, definition)
    captured = files.capture(transformed, source)
    snapshot = captured.snapshot
    require_complete_evidence(snapshot)
    for line in source_differences(config, definition, snapshot):
        logger.warning(f"Источник отличается от выгруженного: {line}. Датасет собирается из выгруженных данных.")
    if snapshot.parent_id != parent_id:
        raise ManagedError("Source parent changed; fetch the managed dataset again")
    files.check_roots(captured.frame, metadata)
    for root in metadata.images.s3_root:
        s3_roots.check_root(root)
    # A first version takes every split from the CSV, whatever the fetch snapshot carries.
    history: dict[str, str] = {} if first else dict(snapshot.assignments)
    history.update(published_assignments(None if first else parent_metadata))
    image_hashes = files.image_hashes(captured.frame)
    frame = resolve_overlaps(captured.frame, image_hashes.identities, definition.overlaps)
    split_frame, replacements = propagate_splits(frame, image_hashes.identities, history)
    # Before validation: cleanup would silently drop rows of one image name in two splits.
    collisions = split_collisions(split_frame, image_hashes.readable)
    inspection = media.inspect(
        split_frame,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
    )
    validation = validate_bundle(split_frame, metadata, inspection=inspection, allow_empty_split=True)
    missing_classes = missing_active_classes(validation.result.clean, metadata)
    blockers = list(validation.blockers)
    if validation.result.requires_cleanup and not clean:
        blockers.append("Cleanup is needed and --no-clean was given.")
    if missing_classes:
        blockers.append(f"Active classes have no bbox: {', '.join(missing_classes)}")
    if collisions:
        blockers.append(f"Image content has rows in several splits: {', '.join(collisions)}")
    validation = dataclasses.replace(validation, blockers=tuple(blockers))
    ready = not blockers
    findings, unmapped = _feedback(split_frame, validation.result, captured)
    tasks = _tasks(validation.result.clean, captured)
    actual_hashes = {
        path: image_hashes.readable[path]
        for path in set(validation.result.clean.get("image_path", []))
        if path in image_hashes.readable
    }
    assignments = rebuild_assignments(validation.result.clean, image_hashes.readable, history)
    prepared_snapshot = snapshot.model_copy(
        update={
            "assignments": assignments,
            "image_hashes": actual_hashes,
            # A first version has no parent in its published evidence either.
            **({"parent_id": None} if first else {}),
        }
    )
    prepared_metadata = metadata.model_copy(
        update={
            "managed": ManagedMetadata(
                name=name,
                definition_hash=definition_hash,
                definition=definition,
                cvat=config.cvat,
                assignments=assignments,
            )
        }
    )
    tasks = tasks.model_copy(update={"managed": prepared_snapshot})
    payload = files.payload_bytes(validation.result.clean, prepared_metadata, tasks) if ready else {}
    record = ManagedRecord(
        name=name,
        parent_id=parent_id,
        parent_version=parent_version,
        findings=findings,
        ready=ready,
        clean=clean,
        first=first,
    )
    report = files.validation_report(
        validation,
        ready=ready,
        findings=findings,
        unmapped=unmapped,
        split_replacements=replacements,
        pending=split_pending(validation.result.clean, directory),
        missing_classes=missing_classes,
        collisions=collisions,
    )
    files.persist(directory, captured, record, payload, report, validation.broken_images)
    return PreparationSummary(directory=directory, ready=ready, report=report)

"""Check a managed preparation as it is now and deliver feedback before publication."""

from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd
from loguru import logger

from cveta2.application.ports.dataset_bundle import (
    ClassApi,
    DatasetStore,
    RootChecks,
    S3Storage,
)
from cveta2.application.ports.managed_feedback import CvatFeedback, FeedbackLedger
from cveta2.application.ports.managed_preparation import (
    LoadedManagedPreparation,
    ManagedPreparationFiles,
)
from cveta2.application.ports.managed_sources import CvatSourceReader, S3CsvReader
from cveta2.application.ports.verification import MediaInspector
from cveta2.application.use_cases.managed_feedback import (
    reconcile_pending,
    report_findings,
)
from cveta2.domain.bundle.classes import registry_mismatches
from cveta2.domain.bundle.models import DatasetMetadata, Publication
from cveta2.domain.bundle.preparation import PAYLOAD_NAMES
from cveta2.domain.bundle.validation import validate_bundle
from cveta2.domain.managed.evidence import (
    SourceAssessment,
    assess_cvat_source,
    assess_s3_source,
    require_complete_evidence,
    source_differences,
)
from cveta2.domain.managed.models import (
    CvatIdentity,
    DatasetDefinition,
    ManagedError,
    ManagedSnapshot,
    ProjectConfig,
    SourceSnapshot,
    dataset_definition,
)
from cveta2.domain.managed.preparation import FeedbackOutcome
from cveta2.domain.verification.models import ValidationOptions


@dataclass(frozen=True)
class ManagedPublicationServices:
    """Explicit effects; composition constructs adapters and ledger ownership."""

    files: ManagedPreparationFiles
    media: MediaInspector
    remote: DatasetStore
    registry: ClassApi
    cvat: CvatSourceReader
    s3: S3CsvReader
    roots: RootChecks
    s3_roots: S3Storage
    feedback: CvatFeedback
    ledger: FeedbackLedger


def _assess_source(
    config: ProjectConfig,
    source: SourceSnapshot,
    services: ManagedPublicationServices,
) -> SourceAssessment:
    """Compare one recorded source with its live state; metadata only, no annotations or CSV bodies."""
    if source.type == "s3-csv":
        return assess_s3_source(source, services.s3.object_identity(source.uri) if source.uri is not None else None)
    if source.project_id is None:
        raise ManagedError("Managed CVAT source lacks project identity")
    project = next((project for project in config.projects.values() if project.id == source.project_id), None)
    if project is None:
        return SourceAssessment(
            warnings=(
                f"{source.name}: проект {source.project_id} больше не описан в конфигурации, задачи не проверены",
            ),
            stale_tasks=frozenset((source.name, task.id) for task in source.tasks.values()),
        )
    state = services.cvat.inspect_project(source.project_id)
    return assess_cvat_source(source, state.tasks, state.labels_fingerprint, project.ignored_task_ids)


def _assess_sources(
    config: ProjectConfig,
    snapshot: ManagedSnapshot,
    services: ManagedPublicationServices,
) -> SourceAssessment:
    """Merge the per-source assessments; a CVAT task completed after fetch stops the command."""
    parts = [_assess_source(config, source, services) for source in snapshot.sources]
    merged = SourceAssessment(
        newly_completed=tuple(task for part in parts for task in part.newly_completed),
        warnings=tuple(line for part in parts for line in part.warnings),
        stale_tasks=frozenset().union(*(part.stale_tasks for part in parts)),
    )
    if merged.newly_completed:
        raise ManagedError(
            f"CVAT tasks completed after fetch: {', '.join(merged.newly_completed)}; fetch the managed dataset again"
        )
    return merged


def _definition_differences(
    config: ProjectConfig, definition: DatasetDefinition, snapshot: ManagedSnapshot
) -> SourceAssessment:
    """Warn about each way the sources of the definition differ from the fetched ones.

    Every recorded task of a source named in a difference is stale.
    """
    lines = source_differences(config, definition, snapshot)
    # Source names cannot contain ":" or spaces, so the prefix names exactly one source.
    changed = {source.name for source in snapshot.sources if any(line.startswith(f"{source.name}: ") for line in lines)}
    return SourceAssessment(
        warnings=tuple(f"Источник отличается от выгруженного: {line}" for line in lines),
        stale_tasks=frozenset(
            (source.name, task.id)
            for source in snapshot.sources
            if source.name in changed
            for task in source.tasks.values()
        ),
    )


def _server(identity: CvatIdentity) -> str:
    """Name a CVAT server and organization for a message."""
    return f"{identity.host} (organization {identity.organization or 'none'})"


def _check_cvat_server(config: ProjectConfig, snapshot: ManagedSnapshot) -> None:
    """Stop unless CVAT sources were fetched from the configured CVAT server and organization.

    Recorded task IDs belong to the fetched server: on another one freshness
    cannot be judged and findings could reach the wrong tasks. A dataset with no
    CVAT source has no such IDs, so its recorded server is not compared.
    ``require_complete_evidence`` has already refused CVAT sources without a server.
    """
    if not any(source.type == "cvat" for source in snapshot.sources):
        return
    if snapshot.cvat is not None and snapshot.cvat != config.cvat:
        raise ManagedError(
            f"CVAT server differs from the one fetched: fetched {_server(snapshot.cvat)}, "
            f"configured {_server(config.cvat)}; fetch the managed dataset again"
        )


def _check_prepared(
    config: ProjectConfig,
    loaded: LoadedManagedPreparation,
    services: ManagedPublicationServices,
) -> SourceAssessment:
    """Check the parent and the sources of ``source-snapshot.yaml``; warn about changed sources.

    Returns the source assessment, whose stale tasks get no feedback; tasks whose
    pending receipts could not be inspected, and tasks of sources that differ from
    the current definition, count as stale too. The payload is not read, so a
    blocked preparation can still report its findings.
    """
    record, snapshot = loaded.record, loaded.captured.snapshot
    require_complete_evidence(snapshot)
    _check_cvat_server(config, snapshot)
    definition = dataset_definition(config, record.name)
    parent = services.remote.latest(definition.clearml.project, definition.clearml.dataset)
    if (parent.dataset_id if parent else None) != record.parent_id:
        raise ManagedError("Latest ClearML parent changed; fetch and prepare again")
    if parent is not None and parent.version != record.parent_version:
        raise ManagedError("ClearML parent version changed; prepare again")
    if parent is not None and parent.metadata_path is None and not record.first:
        raise ManagedError(
            f"Parent {parent.dataset_id} lacks dataset.yaml and is no longer a managed dataset version; "
            "fetch and prepare again, with dataset prepare --first to start a managed lineage"
        )
    differences = _definition_differences(config, definition, snapshot)
    unavailable = reconcile_pending(record.findings, remote=services.feedback, ledger=services.ledger)
    assessment = _assess_sources(config, services.ledger.effective_snapshot(snapshot), services)
    for line in (*differences.warnings, *assessment.warnings):
        logger.warning(f"{line}. Датасет собирается из выгруженных данных.")
    return replace(assessment, stale_tasks=assessment.stale_tasks | differences.stale_tasks | unavailable)


def _report(
    loaded: LoadedManagedPreparation, assessment: SourceAssessment, services: ManagedPublicationServices
) -> FeedbackOutcome:
    """Deliver the recorded findings, except those of tasks that changed after fetch."""
    unmapped = loaded.report.get("unmapped_errors", 0)
    outcome = report_findings(
        loaded.record.findings,
        remote=services.feedback,
        ledger=services.ledger,
        unmapped=unmapped if isinstance(unmapped, int) else 0,
        skip=assessment.stale_tasks,
    )
    if outcome.skipped:
        logger.warning(f"Замечаний не отправлено: {outcome.skipped}: их задачи изменились после fetch")
    return outcome


def _check_current(frame: pd.DataFrame, metadata: DatasetMetadata, services: ManagedPublicationServices) -> None:
    """Validate the current ``dataset.csv`` against its ``dataset.yaml``, local media and roots."""
    services.files.check_roots(frame, metadata)
    for root in metadata.images.local_root:
        services.roots.check_local_root(root)
    for root in metadata.images.s3_root:
        services.s3_roots.check_root(root)
    inspection = services.media.inspect(
        frame,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
    )
    validation = validate_bundle(frame, metadata, inspection=inspection)
    result = validation.result
    if validation.blockers or not result.is_valid or result.requires_cleanup:
        rejected, cleanup, blockers = len(result.broken_row_positions), result.requires_cleanup, validation.blockers
        raise ManagedError(
            f"Prepared dataset.csv does not pass validation: {rejected} rejected rows, "
            f"repairs needed: {'yes' if cleanup else 'no'}, blockers: {'; '.join(blockers) or 'none'}"
        )


def report_prepared(config: ProjectConfig, directory: Path, *, services: ManagedPublicationServices) -> FeedbackOutcome:
    """Deliver the recorded frame findings; a blocked preparation reports too."""
    loaded = services.files.load_prepared(directory)
    assessment = _check_prepared(config, loaded, services)
    return _report(loaded, assessment, services)


def publish_prepared(config: ProjectConfig, directory: Path, *, services: ManagedPublicationServices) -> Publication:
    """Publish the current three payload files once they pass every check and feedback is delivered."""
    loaded = services.files.load_prepared(directory)
    frame, metadata = loaded.frame, loaded.metadata
    if frame is None or metadata is None:
        raise ManagedError("Preparation was blocked and has no payload; see report.json and prepare again")
    assessment = _check_prepared(config, loaded, services)
    _check_current(frame, metadata, services)
    # Only class names and numbers bind the prepared rows; other registry fields may change.
    if names := registry_mismatches(metadata.classes, services.registry.fetch(metadata.api_url)):
        raise ManagedError(f"Class names or numbers differ from the class registry: {', '.join(names)}; prepare again")
    outcome = _report(loaded, assessment, services)
    if outcome.failed:
        raise ManagedError("CVAT feedback delivery failed; retry report-errors before publication")
    # Recheck sources after feedback, acknowledging only proven issue-only writes.
    # Its warnings were printed above; only a task completed meanwhile stops here.
    _assess_sources(config, services.ledger.effective_snapshot(loaded.captured.snapshot), services)
    definition = dataset_definition(config, loaded.record.name)
    latest = services.remote.latest(definition.clearml.project, definition.clearml.dataset)
    if (latest.dataset_id if latest else None) != loaded.record.parent_id:
        raise ManagedError("ClearML parent changed during feedback; prepare again")
    with services.files.stage_payload(loaded.directory) as staging:
        return services.remote.publish(
            definition.clearml.project,
            definition.clearml.dataset,
            None if loaded.record.first else loaded.record.parent_id,
            staging,
            files=PAYLOAD_NAMES,
        )

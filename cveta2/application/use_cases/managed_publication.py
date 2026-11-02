"""Recheck managed preparations and deliver feedback before exact publication."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

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
from cveta2.domain.bundle.models import ApiClass, Publication
from cveta2.domain.bundle.validation import validate_bundle
from cveta2.domain.managed.models import (
    ManagedError,
    ManagedSnapshot,
    ProjectConfig,
    definition_fingerprint,
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
    local_roots: list[str]


def registry_fingerprint(records: list[ApiClass]) -> str:
    """Compare complete class records independent of registry response order."""
    content = [
        record.model_dump(mode="json")
        for record in sorted(records, key=lambda record: record.number)
    ]
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _check_sources(
    config: ProjectConfig,
    snapshot: ManagedSnapshot,
    services: ManagedPublicationServices,
) -> None:
    """Metadata checks never download unchanged CVAT task annotations."""
    for source in snapshot.sources:
        if source.type == "s3-csv":
            if (
                source.uri is None
                or services.s3.read_object(source.uri).content_hash
                != source.content_hash
            ):
                raise ManagedError(f"S3 source changed; fetch again: {source.name}")
            continue
        if source.project_id is None:
            raise ManagedError("Managed CVAT source lacks project identity")
        project = next(
            (
                project
                for project in config.projects.values()
                if project.id == source.project_id
            ),
            None,
        )
        if project is None:
            raise ManagedError("Managed CVAT project no longer configured")
        ignored = {entry.get("id") for entry in project.ignore}
        state = services.cvat.inspect_project(source.project_id)
        live = {str(task.id): task for task in state.tasks if task.id not in ignored}
        if state.labels_fingerprint != source.labels_fingerprint or set(live) != set(
            source.tasks
        ):
            raise ManagedError(f"CVAT source changed; fetch again: {source.name}")
        for key, old in source.tasks.items():
            current = live[key]
            if (
                current.updated_date != old.updated_date
                or current.completed != old.completed
            ):
                raise ManagedError(
                    f"CVAT task changed; fetch again: {source.name}/{old.id}"
                )


def _check_prepared(
    config: ProjectConfig,
    loaded: LoadedManagedPreparation,
    services: ManagedPublicationServices,
) -> None:
    """Check policy, parent, original source facts and clean publication media."""
    record = loaded.record
    if record.definition_hash != definition_fingerprint(config, record.name):
        raise ManagedError("Shared dataset policy changed; prepare again")
    definition = config.datasets[record.name]
    parent = services.remote.latest(
        definition.clearml.project, definition.clearml.dataset
    )
    if (parent.dataset_id if parent else None) != record.parent_id:
        raise ManagedError("Latest ClearML parent changed; fetch and prepare again")
    if parent is not None and parent.version != record.parent_version:
        raise ManagedError("ClearML parent version changed; prepare again")
    records = services.registry.fetch(definition.api_url)
    if registry_fingerprint(records) != record.registry_hash:
        raise ManagedError("Class registry changed; fetch and prepare again")
    reconcile_pending(record.findings, remote=services.feedback, ledger=services.ledger)
    _check_sources(
        config, services.ledger.effective_snapshot(record.snapshot), services
    )
    _check_media(loaded, services)


def _check_media(
    loaded: LoadedManagedPreparation, services: ManagedPublicationServices
) -> None:
    """Revalidate immutable clean bytes against current local media and roots."""
    record = loaded.record
    if loaded.metadata is None:
        return
    if set(services.local_roots) != set(loaded.metadata.images.local_root):
        raise ManagedError("Personal image roots changed; prepare again")
    services.files.check_roots(loaded.frame, loaded.metadata)
    for root in loaded.metadata.images.local_root:
        services.roots.check_local_root(root)
    for root in loaded.metadata.images.s3_root:
        services.s3_roots.check_root(root)
    if services.files.image_hashes(loaded.frame).readable != record.image_hashes:
        raise ManagedError("Prepared images changed; prepare again")
    inspection = services.media.inspect(
        loaded.frame,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
    )
    result = validate_bundle(loaded.frame, loaded.metadata, inspection=inspection)
    if result.blockers or not result.result.is_valid or result.result.requires_cleanup:
        raise ManagedError("Prepared payload no longer passes training validation")


def report_prepared(
    config: ProjectConfig, directory: Path, *, services: ManagedPublicationServices
) -> FeedbackOutcome:
    """Resume traceable frame feedback without changing immutable payload bytes."""
    loaded = services.files.load_prepared(directory)
    _check_prepared(config, loaded, services)
    unmapped = loaded.report.get("unmapped_errors", 0)
    return report_findings(
        loaded.record.findings,
        remote=services.feedback,
        ledger=services.ledger,
        unmapped=unmapped if isinstance(unmapped, int) else 0,
    )


def publish_prepared(
    config: ProjectConfig, directory: Path, *, services: ManagedPublicationServices
) -> Publication:
    """Publish only a ready, fresh, feedback-complete stable three-file snapshot."""
    loaded = services.files.load_prepared(directory)
    if not loaded.record.ready or set(loaded.payload) != {
        "dataset.csv",
        "dataset.yaml",
        "tasks.yaml",
    }:
        raise ManagedError(
            "Preparation is not ready; review diagnostics and accept cleanup"
        )
    _check_prepared(config, loaded, services)
    unmapped = loaded.report.get("unmapped_errors", 0)
    outcome = report_findings(
        loaded.record.findings,
        remote=services.feedback,
        ledger=services.ledger,
        unmapped=unmapped if isinstance(unmapped, int) else 0,
    )
    if outcome.failed:
        raise ManagedError(
            "CVAT feedback delivery failed; retry report-errors before publication"
        )
    # Recheck sources after feedback, acknowledging only proven issue-only writes.
    _check_sources(
        config, services.ledger.effective_snapshot(loaded.record.snapshot), services
    )
    definition = config.datasets[loaded.record.name]
    latest = services.remote.latest(
        definition.clearml.project, definition.clearml.dataset
    )
    if (latest.dataset_id if latest else None) != loaded.record.parent_id:
        raise ManagedError("ClearML parent changed during feedback; prepare again")
    with services.files.stage_payload(loaded.payload) as staging:
        return services.remote.publish(
            definition.clearml.project,
            definition.clearml.dataset,
            loaded.record.parent_id,
            staging,
        )

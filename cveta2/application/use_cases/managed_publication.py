"""Check a managed preparation as it is now and deliver feedback before publication."""

from collections.abc import Mapping, Sequence
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
from cveta2.application.use_cases.dataset_bundle import split_pending
from cveta2.application.use_cases.managed_feedback import (
    reconcile_pending,
    report_findings,
)
from cveta2.application.use_cases.managed_preparation import managed_bookkeeping, published_assignments
from cveta2.domain.bundle.classes import registry_mismatches
from cveta2.domain.bundle.models import DatasetMetadata, DatasetParent, Publication
from cveta2.domain.bundle.preparation import PAYLOAD_NAMES
from cveta2.domain.bundle.validation import images_without_split, missing_active_classes, validate_bundle
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
from cveta2.domain.managed.policies import SplitName, rebuild_assignments, split_collisions, split_conflicts
from cveta2.domain.managed.preparation import FeedbackOutcome
from cveta2.domain.verification.models import ValidationOptions

# How many images or rows one refusal lists before it only counts the rest.
_LISTED = 20


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
) -> tuple[SourceAssessment, DatasetParent | None]:
    """Check the parent and the sources of ``source-snapshot.yaml``; warn about changed sources.

    Returns the source assessment, whose stale tasks get no feedback, and the
    latest version, which is the recorded parent. Tasks whose pending receipts
    could not be inspected, and tasks of sources that differ from the current
    definition, count as stale too. The payload is not read, so a blocked
    preparation can still report its findings.
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
    return replace(assessment, stale_tasks=assessment.stale_tasks | differences.stale_tasks | unavailable), parent


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


def _listed(names: Sequence[str]) -> str:
    """Name at most ``_LISTED`` items, then count the rest."""
    shown = ", ".join(names[:_LISTED])
    return f"{shown} and {len(names) - _LISTED} more" if len(names) > _LISTED else shown


def _listing(items: Sequence[str]) -> str:
    """One indented item per line, at most ``_LISTED`` of them, then the count of the rest."""
    lines = [f"  {item}" for item in items[:_LISTED]]
    if len(items) > _LISTED:
        lines.append(f"  and {len(items) - _LISTED} more")
    return "\n".join(lines)


def _not_ready(pending: Sequence[str]) -> ManagedError:
    """Refuse with the ``pending`` lines ``dataset prepare`` reported for the same rows."""
    return ManagedError(f"Prepared dataset.csv is not ready for publication: {'; '.join(pending)}")


def _check_bindings(frame: pd.DataFrame, metadata: DatasetMetadata, services: ManagedPublicationServices) -> None:
    """Check the staged ``dataset.yaml`` against the class registry, and the rows against its roots.

    Runs before any image is read, so a path outside the roots is never opened.
    """
    # Only class names and numbers bind the rows; other registry fields may change.
    if names := registry_mismatches(metadata.classes, services.registry.fetch(metadata.api_url)):
        raise ManagedError(f"Class names or numbers differ from the class registry: {', '.join(names)}; prepare again")
    services.files.check_roots(frame, metadata)
    for root in metadata.images.local_root:
        services.roots.check_local_root(root)
    for root in metadata.images.s3_root:
        services.s3_roots.check_root(root)


def _check_current(
    frame: pd.DataFrame,
    metadata: DatasetMetadata,
    directory: Path,
    hashes: Mapping[str, str],
    services: ManagedPublicationServices,
) -> None:
    """Check the staged rows of the preparation in *directory* against their ``dataset.yaml`` and media.

    In order: one split per image content, filled splits, validation,
    trainability and class coverage.
    """
    # Before validation, which would reject rows of one image name in two splits as ordinary row errors.
    if collisions := split_collisions(frame, hashes):
        raise ManagedError(
            f"Image content has rows in several splits: {', '.join(collisions)}; one image may have one split"
        )
    if images_without_split(frame):
        raise _not_ready(split_pending(frame, directory))
    inspection = services.media.inspect(
        frame,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
    )
    # Every split is filled, so this mode only leaves the trainability gaps to the pending lines below.
    validation = validate_bundle(frame, metadata, inspection=inspection, allow_empty_split=True)
    result = validation.result
    if validation.blockers or not result.is_valid or result.requires_cleanup:
        rejected, cleanup = len(result.broken_row_positions), result.requires_cleanup
        problems = [
            *validation.blockers,
            *(
                f"row {issue.row_position}: {issue.message}" if issue.row_position is not None else issue.message
                for issue in result.issues
            ),
        ]
        raise ManagedError(
            f"Prepared dataset.csv does not pass validation: {rejected} rejected rows, "
            f"repairs needed: {'yes' if cleanup else 'no'}\n{_listing(problems)}"
        )
    if pending := split_pending(result.clean, directory):
        raise _not_ready(pending)
    if names := missing_active_classes(frame, metadata):
        raise ManagedError(
            f"Active classes have no bbox: {', '.join(names)}; "
            "mark them empty: true in dataset.yaml or add rows with them"
        )


def _published(
    loaded: LoadedManagedPreparation, parent: DatasetParent | None, services: ManagedPublicationServices
) -> dict[str, SplitName]:
    """Return the splits the parent published; a first version reads no parent at all."""
    # ``_check_prepared`` refused a parent without dataset.yaml unless the preparation is a first version.
    if loaded.record.first or parent is None or parent.metadata_path is None:
        return {}
    return published_assignments(services.files.read_metadata(parent.metadata_path))


def report_prepared(config: ProjectConfig, directory: Path, *, services: ManagedPublicationServices) -> FeedbackOutcome:
    """Deliver the recorded frame findings; a blocked preparation reports too."""
    loaded = services.files.load_prepared(directory)
    assessment, _parent = _check_prepared(config, loaded, services)
    return _report(loaded, assessment, services)


def publish_prepared(
    config: ProjectConfig,
    directory: Path,
    *,
    services: ManagedPublicationServices,
    force_resplit: bool = False,
) -> Publication:
    """Publish the three payload files once they pass every check and feedback is delivered.

    The files are copied before the checks, so exactly the checked rows are published. The
    split assignments, task lists and the rest of the derived bookkeeping are rebuilt from those
    rows and written back to *directory* too. A published image keeps its split unless
    *force_resplit*.
    """
    loaded = services.files.load_prepared(directory)
    if loaded.frame is None or loaded.metadata is None:
        raise ManagedError("Preparation was blocked and has no payload; see report.json and prepare again")
    assessment, parent = _check_prepared(config, loaded, services)
    record = loaded.record
    definition = dataset_definition(config, record.name)
    with services.files.stage_payload(loaded.directory) as staging:
        frame = services.files.read_rows(staging / "dataset.csv")
        metadata = services.files.read_metadata(staging / "dataset.yaml")
        _check_bindings(frame, metadata, services)
        hashes = services.files.image_hashes(frame).readable
        _check_current(frame, metadata, loaded.directory, hashes, services)
        published = _published(loaded, parent, services)
        if not force_resplit and (conflicts := split_conflicts(frame, hashes, published)):
            moved = [f"{name} ({was} → {now})" for name, was, now in conflicts]
            raise ManagedError(
                f"Images published in the parent must keep their split: {_listed(moved)}; "
                "restore the split in dataset.csv or pass --force-resplit"
            )
        # Removed images keep their assignments; with force_resplit the rows' splits replace the published ones.
        base = {} if record.first else {**loaded.captured.snapshot.assignments, **published}
        metadata, tasks = managed_bookkeeping(
            config,
            record.name,
            definition,
            frame,
            metadata,
            loaded.captured,
            assignments=rebuild_assignments(frame, hashes, base),
            image_hashes=hashes,
            first=record.first,
        )
        for target in (staging, loaded.directory):
            services.files.write_bookkeeping(target, metadata, tasks)
        outcome = _report(loaded, assessment, services)
        if outcome.failed:
            raise ManagedError("CVAT feedback delivery failed; retry report-errors before publication")
        # Recheck sources after feedback, acknowledging only proven issue-only writes.
        # Its warnings were printed above; only a task completed meanwhile stops here.
        _assess_sources(config, services.ledger.effective_snapshot(loaded.captured.snapshot), services)
        latest = services.remote.latest(definition.clearml.project, definition.clearml.dataset)
        if (latest.dataset_id if latest else None) != record.parent_id:
            raise ManagedError("ClearML parent changed during feedback; prepare again")
        return services.remote.publish(
            definition.clearml.project,
            definition.clearml.dataset,
            None if record.first else record.parent_id,
            staging,
            files=PAYLOAD_NAMES,
            output_uri=definition.clearml.output_uri,
        )

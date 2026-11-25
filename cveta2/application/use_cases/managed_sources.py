"""Assemble complete managed candidates while reusing unchanged task records."""

import pandas as pd

from cveta2.application.ports.managed_sources import (
    CvatSourceReader,
    S3CsvReader,
    SourceFiles,
)
from cveta2.domain.class_registry import ApiClass, registry_fingerprint
from cveta2.domain.managed.evidence import consistent_evidence, require_complete_evidence
from cveta2.domain.managed.models import (
    CvatIdentity,
    DatasetDefinition,
    ManagedError,
    ManagedSnapshot,
    ProjectConfig,
    ProjectDefinition,
    SourceDefinition,
    SourceSnapshot,
    TaskSnapshot,
    source_fingerprint,
)


def _cvat_source(  # noqa: PLR0913
    source: SourceDefinition,
    project: ProjectDefinition,
    previous: SourceSnapshot | None,
    *,
    reader: CvatSourceReader,
    files: SourceFiles,
    refresh: bool,
) -> SourceSnapshot:
    state = reader.inspect_project(project.id)
    previous_tasks = (
        previous.tasks
        if previous is not None
        and previous.labels is not None
        and previous.type == "cvat"
        and previous.project_id == project.id
        and previous.labels_fingerprint == state.labels_fingerprint
        and not refresh
        else {}
    )
    ignored = project.ignored_task_ids
    tasks: dict[str, TaskSnapshot] = {}
    fetched: list[int] = []
    reused: list[int] = []
    inventory = sorted(state.tasks, key=lambda task: task.id)
    if len({task.id for task in inventory}) != len(inventory):
        raise ManagedError(f"Duplicate task ids in source {source.name}")
    for live in inventory:
        if live.id in ignored:
            continue
        old = previous_tasks.get(str(live.id))
        if (
            old is not None
            and old.completed
            and live.completed
            and old.updated_date == live.updated_date
            and bool(old.tables)
        ):
            captured = old
            reused.append(live.id)
        else:
            captured = reader.read_task(project.id, live)
            if captured.id != live.id or captured.updated_date != live.updated_date:
                raise ManagedError(f"Task changed during fetch: {source.name}/{live.id}")
            fetched.append(live.id)
        tasks[str(live.id)] = captured
    return SourceSnapshot(
        name=source.name,
        type="cvat",
        project_id=project.id,
        tasks=tasks,
        labels_fingerprint=state.labels_fingerprint,
        labels=state.labels,
        tables=files.project_tables(list(tasks.values())),
        fetched=fetched,
        reused=reused,
    )


def fetch_sources(  # noqa: PLR0913
    config: ProjectConfig,
    definition: DatasetDefinition,
    *,
    registry: list[ApiClass],
    cvat: CvatSourceReader,
    s3: S3CsvReader,
    files: SourceFiles,
    previous: ManagedSnapshot | None = None,
    previous_cvat: CvatIdentity | None = None,
    parent_id: str | None = None,
    refresh: bool = False,
) -> tuple[ManagedSnapshot, pd.DataFrame]:
    """Capture every configured source; any read failure aborts the candidate.

    Previously published records are a source cache, never transformed training
    rows. Fresh inventory removes deleted tasks; per-source partitioning keeps
    task IDs from one project from superseding records in another.

    Reuse is decided per source: a source keeps its previous tasks while its
    name, type, CVAT project and labels match, and ignored tasks are skipped
    per task, so editing one source refetches at most that source. Every source
    is reset only by ``refresh``, legacy or inconsistent evidence (records
    missing or not matching their fingerprints), a class registry change or a
    change of the CVAT host or organization. ``previous_cvat`` is the identity
    the previous snapshot was captured under and must come from the same
    publication as ``previous``; when it is unknown, any source definition hash
    mismatch conservatively resets every source.
    """
    registry_hash = registry_fingerprint(registry)
    definition_hash = source_fingerprint(config, definition)
    legacy = previous is not None and not consistent_evidence(previous)
    invalidated = (
        refresh
        or previous is None
        or legacy
        or previous.registry_hash != registry_hash
        or (previous_cvat != config.cvat if previous_cvat is not None else previous.definition_hash != definition_hash)
    )
    old_sources = {source.name: source for source in previous.sources} if previous else {}
    sources: list[SourceSnapshot] = []
    for source in definition.sources:
        if source.type == "cvat":
            if source.project is None:
                raise ManagedError(f"Missing CVAT project for source {source.name}")
            snapshot = _cvat_source(
                source,
                config.projects[source.project],
                old_sources.get(source.name),
                reader=cvat,
                files=files,
                refresh=invalidated,
            )
        else:
            if source.uri is None:
                raise ManagedError(f"Missing S3 object for source {source.name}")
            captured = s3.read_object(source.uri)
            snapshot = SourceSnapshot(
                name=source.name,
                type="s3-csv",
                uri=source.uri,
                content_hash=captured.content_hash,
                etag=captured.etag,
                version_id=captured.version_id,
                tables=files.csv_tables(captured.content, source.uri),
            )
        sources.append(snapshot)
    frames = [files.source_frame(source) for source in sources]
    frame = pd.concat(frames, ignore_index=True, sort=False)
    managed = ManagedSnapshot(
        definition_hash=definition_hash,
        registry_hash=registry_hash,
        registry=sorted(registry, key=lambda record: record.number),
        cvat=config.cvat,
        parent_id=parent_id,
        sources=sources,
        assignments=previous.assignments if previous else {},
        image_hashes=previous.image_hashes if previous else {},
    )
    require_complete_evidence(managed)
    return managed, frame

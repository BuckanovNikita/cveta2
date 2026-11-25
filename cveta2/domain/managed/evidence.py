"""Source evidence: presence and consistency of records, and freshness of live sources."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from cveta2.domain.class_registry import registry_fingerprint
from cveta2.domain.managed.models import (
    DatasetDefinition,
    ManagedError,
    ManagedSnapshot,
    ProjectConfig,
    SourceSnapshot,
    TaskSnapshot,
)
from cveta2.domain.models import LabelInfo


@dataclass(frozen=True)
class S3ObjectIdentity:
    """What identifies an S3 object without reading it; both values are opaque."""

    etag: str | None
    version_id: str | None


@dataclass(frozen=True)
class SourceAssessment:
    """How live sources differ from what fetch recorded.

    ``newly_completed`` names ``<source>/<task id>`` of tasks completed since
    fetch, which stop a command. ``warnings`` describe every other difference,
    in Russian, one line each. ``stale_tasks`` are the ``(source name, task id)``
    pairs whose findings must not be delivered.
    """

    newly_completed: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    stale_tasks: frozenset[tuple[str, int]] = frozenset()


def labels_fingerprint(labels: list[LabelInfo]) -> str:
    """Bind full CVAT definitions independently of top-level response order."""
    content = [label.model_dump(mode="json") for label in sorted(labels, key=lambda label: label.id)]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require_complete_evidence(snapshot: ManagedSnapshot) -> None:
    """Keep old snapshots readable, but require the full records before preparation or publication."""
    if snapshot.registry is None:
        raise ManagedError("Source snapshot lacks class-registry records; fetch and prepare again")
    if snapshot.cvat is None and any(source.type == "cvat" for source in snapshot.sources):
        raise ManagedError("Source snapshot lacks the CVAT server identity; fetch and prepare again")
    for source in snapshot.sources:
        if source.type == "cvat" and source.labels is None:
            raise ManagedError(f"Source snapshot lacks CVAT label definitions: {source.name}; fetch and prepare again")


def consistent_evidence(snapshot: ManagedSnapshot) -> bool:
    """Say whether the full records are present and match the fingerprints stored next to them."""
    if snapshot.registry is None or registry_fingerprint(snapshot.registry) != snapshot.registry_hash:
        return False
    return all(
        source.labels is not None and labels_fingerprint(source.labels) == source.labels_fingerprint
        for source in snapshot.sources
        if source.type == "cvat"
    )


def assess_cvat_source(
    source: SourceSnapshot,
    live_tasks: Sequence[TaskSnapshot],
    live_labels_fingerprint: str,
    ignored: frozenset[int],
) -> SourceAssessment:
    """Compare a CVAT source recorded at fetch with its live tasks and labels.

    Only a task completed now that fetch did not record as completed stops a
    command. A task that was deleted, ignored, reopened or edited since fetch,
    and every task of a source whose labels changed, is stale: its findings are
    skipped.
    """
    live = {task.id: task for task in live_tasks if task.id not in ignored}
    recorded = {task.id: task for task in source.tasks.values()}
    newly_completed: list[str] = []
    warnings: list[str] = []
    stale: set[tuple[str, int]] = set()
    for task_id in sorted(live.keys() | recorded.keys()):
        now, then = live.get(task_id), recorded.get(task_id)
        if now is None:
            gone = "теперь игнорируется" if task_id in ignored else "удалена"
            warnings.append(f"{source.name}: задача {task_id} {gone}")
            stale.add((source.name, task_id))
        elif now.completed and (then is None or not then.completed):
            newly_completed.append(f"{source.name}/{task_id}")
        elif then is None:
            warnings.append(f"{source.name}: новая незавершённая задача {task_id}")
        elif then.completed and not now.completed:
            warnings.append(f"{source.name}: задача {task_id} переоткрыта")
            stale.add((source.name, task_id))
        elif now.updated_date != then.updated_date:
            warnings.append(f"{source.name}: задача {task_id} изменена после fetch")
            stale.add((source.name, task_id))
    if labels_fingerprint(source.labels or []) != live_labels_fingerprint:
        warnings.append(f"{source.name}: изменились метки проекта")
        stale.update((source.name, task_id) for task_id in recorded)
    return SourceAssessment(tuple(newly_completed), tuple(warnings), frozenset(stale))


def assess_s3_source(source: SourceSnapshot, live: S3ObjectIdentity | None) -> SourceAssessment:
    """Compare an S3 CSV source recorded at fetch with the object there now.

    ``live`` is ``None`` when the object could not be named; it counts as
    another object. S3 rows never map to CVAT findings, so nothing is stale.
    """
    if source.etag is None and source.version_id is None:
        return SourceAssessment(warnings=(f"{source.name}: в снимке нет ETag и версии, проверить объект нельзя",))
    if live is None or (live.etag, live.version_id) != (source.etag, source.version_id):
        return SourceAssessment(warnings=(f"{source.name}: в S3 лежит другой объект (ETag или версия)",))
    return SourceAssessment()


def source_differences(
    config: ProjectConfig,
    definition: DatasetDefinition,
    snapshot: ManagedSnapshot,
) -> tuple[str, ...]:
    """Describe, in Russian, how the snapshot's sources differ from the current definition.

    Sources are matched by name and compared on type, resolved CVAT project id
    and URI; the snapshot value is the old one, the definition value the new one.
    """
    current: dict[str, dict[str, object]] = {}
    for source in definition.sources:
        project = config.projects.get(source.project) if source.project is not None else None
        current[source.name] = {
            "type": source.type,
            "project_id": project.id if project is not None else None,
            "uri": source.uri,
        }
    recorded = {
        source.name: {"type": source.type, "project_id": source.project_id, "uri": source.uri}
        for source in snapshot.sources
    }
    lines = [f"{name}: только в снимке" for name in recorded.keys() - current.keys()]
    lines += [f"{name}: только в описании" for name in current.keys() - recorded.keys()]
    for name in current.keys() & recorded.keys():
        lines += [
            f"{name}: {field} {recorded[name][field]} → {current[name][field]}"
            for field in ("type", "project_id", "uri")
            if recorded[name][field] != current[name][field]
        ]
    return tuple(sorted(lines))

"""Full source definitions required for new managed preparation/publication."""

import hashlib
import json

from cveta2.domain.class_registry import registry_fingerprint
from cveta2.domain.managed.models import DatasetDefinition, ManagedError, ManagedSnapshot, ProjectConfig
from cveta2.domain.models import LabelInfo


def labels_fingerprint(labels: list[LabelInfo]) -> str:
    """Bind full CVAT definitions independently of top-level response order."""
    content = [label.model_dump(mode="json") for label in sorted(labels, key=lambda label: label.id)]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require_complete_evidence(snapshot: ManagedSnapshot) -> None:
    """Keep old snapshots readable, but require fresh capture before publication."""
    if snapshot.registry is None:
        raise ManagedError("Source snapshot lacks class-registry records; fetch and prepare again")
    if registry_fingerprint(snapshot.registry) != snapshot.registry_hash:
        raise ManagedError("Class-registry records do not match their fingerprint; fetch and prepare again")
    for source in snapshot.sources:
        if source.type != "cvat":
            continue
        if source.labels is None:
            raise ManagedError(f"Source snapshot lacks CVAT label definitions: {source.name}; fetch and prepare again")
        if labels_fingerprint(source.labels) != source.labels_fingerprint:
            raise ManagedError(
                f"CVAT label definitions do not match their fingerprint: {source.name}; fetch and prepare again"
            )


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

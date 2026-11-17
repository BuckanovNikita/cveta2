"""Full source definitions required for new managed preparation/publication."""

import hashlib
import json

from cveta2.domain.class_registry import registry_fingerprint
from cveta2.domain.managed.models import ManagedError, ManagedSnapshot
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

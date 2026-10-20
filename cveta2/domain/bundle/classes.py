"""Pure API class identity and historical name reconciliation."""

from collections.abc import Sequence

from cveta2.domain.bundle.models import (
    ApiClass,
    ClassChange,
    ClassInfo,
    ClassUpdate,
    UploadError,
)


def class_lookup(classes: dict[str, ClassInfo]) -> dict[str, str]:
    """Resolve canonical and historical names, rejecting ambiguous identities."""
    lookup: dict[str, str] = {}
    identities: set[int] = set()
    for name, info in classes.items():
        if not name:
            raise UploadError("Class canonical names must be nonempty")
        if info.prod_id in identities:
            raise UploadError(f"Duplicate class prod_id: {info.prod_id}")
        identities.add(info.prod_id)
        for alias in [name, *info.alt_names]:
            if alias in lookup and lookup[alias] != name:
                raise UploadError(f"Ambiguous class name or alias: {alias!r}")
            lookup[alias] = name
    return lookup


def reconcile_classes(
    previous: dict[str, ClassInfo], records: Sequence[ApiClass]
) -> ClassUpdate:
    """Keep policy by API number while recording canonical-name transitions."""
    class_lookup(previous)
    by_number: dict[int, ApiClass] = {}
    names: set[str] = set()
    for record in records:
        if record.number in by_number:
            raise UploadError(f"Duplicate API class number: {record.number}")
        if record.name in names:
            raise UploadError(f"Duplicate API class name: {record.name!r}")
        by_number[record.number] = record
        names.add(record.name)
    old_by_number = {info.prod_id: (name, info) for name, info in previous.items()}
    missing = sorted(old_by_number.keys() - by_number.keys())
    if missing:
        raise UploadError(f"Previous class prod_id values missing from API: {missing}")
    classes: dict[str, ClassInfo] = {}
    changes: list[ClassChange] = []
    for record in records:
        old = old_by_number.get(record.number)
        if old is None:
            classes[record.name] = ClassInfo(prod_id=record.number)
            changes.append(ClassChange("added", record.number, record.name))
            continue
        old_name, info = old
        aliases = list(info.alt_names)
        if old_name != record.name:
            aliases.append(old_name)
            changes.append(ClassChange("renamed", record.number, record.name, old_name))
        aliases = list(
            dict.fromkeys(alias for alias in aliases if alias != record.name)
        )
        classes[record.name] = ClassInfo(
            prod_id=record.number, empty=info.empty, alt_names=aliases
        )
    class_lookup(classes)
    return ClassUpdate(classes, tuple(changes))

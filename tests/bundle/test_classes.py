"""Class API identity and persisted alias reconciliation contracts."""

import pytest

from cveta2.domain.bundle.classes import class_lookup, reconcile_classes
from cveta2.domain.bundle.models import ApiClass, ClassInfo, UploadError


def api(number: int, name: str, *, internal_id: int = 100) -> ApiClass:
    return ApiClass(
        id=internal_id,
        number=number,
        name=name,
        techClass=False,
        isPeriodical=False,
        isCritical=False,
        threshold=0.5,
    )


def test_rename_chain_and_reversion_preserve_empty_history_and_inputs() -> None:
    original = {"a": ClassInfo(prod_id=7, empty=True, alt_names=["old", "old"])}
    first = reconcile_classes(original, [api(7, "b", internal_id=500)])
    assert first.classes["b"] == ClassInfo(
        prod_id=7, empty=True, alt_names=["old", "a"]
    )
    second = reconcile_classes(first.classes, [api(7, "a")])
    assert second.classes["a"].alt_names == ["old", "b"]
    assert second.changes[0].old_name == "b"
    assert second.changes[0].kind == "renamed"
    assert original["a"].alt_names == ["old", "old"]
    assert class_lookup(second.classes) == {"a": "a", "old": "a", "b": "a"}


def test_added_class_defaults_and_unchanged_records() -> None:
    update = reconcile_classes({"a": ClassInfo(prod_id=1)}, [api(1, "a"), api(2, "b")])
    assert update.classes["b"] == ClassInfo(prod_id=2)
    assert [
        (change.kind, change.prod_id, change.name) for change in update.changes
    ] == [("added", 2, "b")]


@pytest.mark.parametrize(
    "records", [[api(1, "a"), api(1, "b")], [api(1, "a"), api(2, "a")], []]
)
def test_invalid_api_or_missing_identity_blocks(records: list[ApiClass]) -> None:
    with pytest.raises(UploadError):
        reconcile_classes({"a": ClassInfo(prod_id=1)}, records)


@pytest.mark.parametrize(
    "classes",
    [
        {"a": ClassInfo(prod_id=1), "b": ClassInfo(prod_id=1)},
        {"a": ClassInfo(prod_id=1, alt_names=["b"]), "b": ClassInfo(prod_id=2)},
        {
            "a": ClassInfo(prod_id=1, alt_names=["x"]),
            "b": ClassInfo(prod_id=2, alt_names=["x"]),
        },
    ],
)
def test_previous_identity_and_name_ambiguity_blocks(
    classes: dict[str, ClassInfo],
) -> None:
    with pytest.raises(UploadError):
        reconcile_classes(classes, [api(1, "a"), api(2, "b")])
    with pytest.raises(UploadError):
        class_lookup(classes)


def test_api_rename_cannot_steal_another_identity_alias() -> None:
    previous = {"a": ClassInfo(prod_id=1), "b": ClassInfo(prod_id=2, alt_names=["old"])}
    with pytest.raises(UploadError):
        reconcile_classes(previous, [api(1, "old"), api(2, "b")])

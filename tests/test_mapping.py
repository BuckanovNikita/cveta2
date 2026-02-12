"""Unit tests for label/attribute mapping helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cveta2._client.mapping import _build_label_maps

if TYPE_CHECKING:
    from tests.fixtures.fake_cvat_project import LoadedFixtures


def test_build_label_maps_from_fixtures(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """80 COCO labels from coco8-dev are mapped id -> name correctly."""
    _project, _tasks, labels, _task_data = coco8_fixtures
    label_names, _attr_names = _build_label_maps(labels)

    assert len(label_names) == 80
    # Spot-check a few well-known COCO classes
    name_set = set(label_names.values())
    for expected in ("person", "car", "dog", "cat", "bicycle"):
        assert expected in name_set, f"{expected!r} not found in label names"

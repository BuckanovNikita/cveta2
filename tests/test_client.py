"""Tests for client.py internal helpers."""

from __future__ import annotations

from types import SimpleNamespace

from cveta2._client.dtos import RawDataMeta, RawFrame
from cveta2.client import _build_name_to_frame


class TestBuildNameToFrame:
    """Tests for _build_name_to_frame() basename fallback."""

    def test_prefixed_paths_resolve_by_basename(self) -> None:
        data_meta = SimpleNamespace(
            frames=[
                SimpleNamespace(name="project/images/2026-03/img.jpg"),
                SimpleNamespace(name="project/images/deep/nested/img2.jpg"),
            ]
        )

        mapping = _build_name_to_frame(data_meta)

        # Full paths are mapped
        assert mapping["project/images/2026-03/img.jpg"] == 0
        assert mapping["project/images/deep/nested/img2.jpg"] == 1

        # Basenames are also mapped
        assert mapping["img.jpg"] == 0
        assert mapping["img2.jpg"] == 1

    def test_flat_names(self) -> None:
        data_meta = SimpleNamespace(
            frames=[
                SimpleNamespace(name="img1.jpg"),
                SimpleNamespace(name="img2.jpg"),
            ]
        )

        mapping = _build_name_to_frame(data_meta)

        assert mapping["img1.jpg"] == 0
        assert mapping["img2.jpg"] == 1

    def test_basename_collision_keeps_first(self) -> None:
        data_meta = SimpleNamespace(
            frames=[
                SimpleNamespace(name="2026-01/img.jpg"),
                SimpleNamespace(name="2026-02/img.jpg"),
            ]
        )

        mapping = _build_name_to_frame(data_meta)

        # Full paths are both mapped
        assert mapping["2026-01/img.jpg"] == 0
        assert mapping["2026-02/img.jpg"] == 1

        # Basename keeps first occurrence
        assert mapping["img.jpg"] == 0

    def test_works_with_raw_data_meta(self) -> None:
        raw = RawDataMeta(
            frames=[
                RawFrame(name="2026-03/img.jpg", width=100, height=100),
            ]
        )
        mapping = _build_name_to_frame(raw)
        assert mapping["2026-03/img.jpg"] == 0
        assert mapping["img.jpg"] == 0

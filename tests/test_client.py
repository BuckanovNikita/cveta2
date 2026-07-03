"""Tests for the build_name_to_frame assembly helper."""

from __future__ import annotations

from cveta2._client.assembly import build_name_to_frame
from cveta2._client.dtos import RawDataMeta, RawFrame


def _meta(*names: str) -> RawDataMeta:
    return RawDataMeta(
        frames=[RawFrame(name=name, width=100, height=100) for name in names]
    )


class TestBuildNameToFrame:
    """Tests for build_name_to_frame() basename fallback."""

    def test_prefixed_paths_resolve_by_basename(self) -> None:
        mapping = build_name_to_frame(
            _meta(
                "project/images/2026-03/img.jpg",
                "project/images/deep/nested/img2.jpg",
            )
        )

        assert mapping["project/images/2026-03/img.jpg"] == 0
        assert mapping["project/images/deep/nested/img2.jpg"] == 1
        assert mapping["img.jpg"] == 0
        assert mapping["img2.jpg"] == 1

    def test_flat_names(self) -> None:
        mapping = build_name_to_frame(_meta("img1.jpg", "img2.jpg"))

        assert mapping["img1.jpg"] == 0
        assert mapping["img2.jpg"] == 1

    def test_basename_collision_keeps_first(self) -> None:
        mapping = build_name_to_frame(_meta("2026-01/img.jpg", "2026-02/img.jpg"))

        assert mapping["2026-01/img.jpg"] == 0
        assert mapping["2026-02/img.jpg"] == 1
        assert mapping["img.jpg"] == 0

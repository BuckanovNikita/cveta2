"""Tests for the pure assembly helpers extracted from ``client``."""

from __future__ import annotations

import pandas as pd

from cveta2._client.assembly import (
    build_name_to_frame,
    build_task_issues,
    build_upload_shapes,
)
from cveta2._client.dtos import RawDataMeta, RawFrame, RawJob


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


class TestBuildUploadShapes:
    """Tests for build_upload_shapes() row -> NewShape translation."""

    @staticmethod
    def _df(rows: list[dict[str, object]]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_valid_rows_become_shapes(self) -> None:
        df = self._df(
            [
                {
                    "image_name": "a.jpg",
                    "instance_label": "car",
                    "bbox_x_tl": 1.0,
                    "bbox_y_tl": 2.0,
                    "bbox_x_br": 3.0,
                    "bbox_y_br": 4.0,
                }
            ]
        )
        result = build_upload_shapes(df, {"a.jpg": 5}, {"car": 9})

        assert len(result.shapes) == 1
        assert result.shapes[0].frame == 5
        assert result.shapes[0].label_id == 9
        assert result.shapes[0].points == [1.0, 2.0, 3.0, 4.0]
        assert result.unknown_images == 0
        assert result.unknown_labels == []

    def test_unknown_image_and_label_are_reported(self) -> None:
        df = self._df(
            [
                {
                    "image_name": "missing.jpg",
                    "instance_label": "car",
                    "bbox_x_tl": 1.0,
                    "bbox_y_tl": 2.0,
                    "bbox_x_br": 3.0,
                    "bbox_y_br": 4.0,
                },
                {
                    "image_name": "a.jpg",
                    "instance_label": "ghost",
                    "bbox_x_tl": 1.0,
                    "bbox_y_tl": 2.0,
                    "bbox_x_br": 3.0,
                    "bbox_y_br": 4.0,
                },
            ]
        )
        result = build_upload_shapes(df, {"a.jpg": 0}, {"car": 1})

        assert result.shapes == []
        assert result.unknown_images == 1
        assert result.unknown_labels == ["ghost"]

    def test_rows_without_full_bbox_are_ignored(self) -> None:
        df = self._df(
            [
                {
                    "image_name": "a.jpg",
                    "instance_label": "car",
                    "bbox_x_tl": 1.0,
                    "bbox_y_tl": None,
                    "bbox_x_br": 3.0,
                    "bbox_y_br": 4.0,
                }
            ]
        )
        result = build_upload_shapes(df, {"a.jpg": 0}, {"car": 1})

        assert result.shapes == []
        assert result.unknown_images == 0


class TestBuildTaskIssues:
    """Tests for build_task_issues() row -> NewIssue translation."""

    @staticmethod
    def _row(image_name: str) -> dict[str, object]:
        return {
            "image_name": image_name,
            "issue_text": "fix this",
            "bbox_x_tl": 1.0,
            "bbox_y_tl": 2.0,
            "bbox_x_br": 3.0,
            "bbox_y_br": 4.0,
        }

    def test_valid_row_becomes_issue(self) -> None:
        df = pd.DataFrame([self._row("a.jpg")])
        jobs = [RawJob(id=7, start_frame=0, stop_frame=10)]

        result = build_task_issues(df, {"a.jpg": 3}, jobs)

        assert len(result.issues) == 1
        assert result.issues[0].job_id == 7
        assert result.issues[0].frame == 3
        assert result.issues[0].position == [1.0, 2.0, 3.0, 4.0]
        assert result.issues[0].message == "fix this"

    def test_unknown_image_missing_bbox_and_no_job_reported(self) -> None:
        rows = [self._row("known.jpg"), self._row("unknown.jpg")]
        rows[0]["bbox_x_br"] = None  # incomplete bbox
        df = pd.DataFrame(rows)
        jobs: list[RawJob] = []  # no job covers any frame

        result = build_task_issues(df, {"known.jpg": 0}, jobs)

        assert result.issues == []
        assert result.missing_bbox == ["known.jpg"]
        assert result.unknown_images == ["unknown.jpg"]

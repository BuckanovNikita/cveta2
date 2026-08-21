"""Tests for the pure assembly helpers extracted from ``client``."""

from __future__ import annotations

import pandas as pd

from cveta2._client.assembly import (
    build_name_to_frame,
    build_task_issues,
    build_upload_shapes,
    find_job_for_frame,
    task_to_records,
)
from cveta2._client.dtos import (
    RawAnnotations,
    RawAttribute,
    RawDataMeta,
    RawFrame,
    RawIssue,
    RawJob,
)
from cveta2.models import BBoxAnnotation, DeletedImage, ImageWithoutAnnotations
from tests.helpers import make_raw_shape, make_task


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

    def test_bbox_completeness_is_decided_per_row(self) -> None:
        """``.all(axis=1)`` — one incomplete row must not disqualify the rest.

        With ``axis=None`` the frame reduces to a single scalar, so one NaN
        anywhere drops every shape. A test whose rows are uniformly complete
        cannot see the difference.
        """
        df = self._df(
            [
                {
                    "image_name": "a.jpg",
                    "instance_label": "car",
                    "bbox_x_tl": 1.0,
                    "bbox_y_tl": 2.0,
                    "bbox_x_br": 3.0,
                    "bbox_y_br": 4.0,
                },
                {
                    "image_name": "b.jpg",
                    "instance_label": "car",
                    "bbox_x_tl": 1.0,
                    "bbox_y_tl": None,
                    "bbox_x_br": 3.0,
                    "bbox_y_br": 4.0,
                },
            ]
        )
        result = build_upload_shapes(df, {"a.jpg": 0, "b.jpg": 1}, {"car": 1})

        assert [s.frame for s in result.shapes] == [0]

    def test_skipped_rows_do_not_stop_the_scan(self) -> None:
        """Both skip branches ``continue``; a ``break`` would drop later rows.

        Also pins ``unknown_images += 1`` against a plain assignment by using
        two unknown images rather than one.
        """
        rows: list[dict[str, object]] = [
            {
                "image_name": name,
                "instance_label": label,
                "bbox_x_tl": 1.0,
                "bbox_y_tl": 2.0,
                "bbox_x_br": 3.0,
                "bbox_y_br": 4.0,
            }
            for name, label in [
                ("missing1.jpg", "car"),
                ("missing2.jpg", "car"),
                ("a.jpg", "ghost"),
                ("a.jpg", "car"),
            ]
        ]
        result = build_upload_shapes(self._df(rows), {"a.jpg": 0}, {"car": 1})

        assert len(result.shapes) == 1
        assert result.unknown_images == 2
        assert result.unknown_labels == ["ghost"]


class TestFindJobForFrame:
    """Tests for find_job_for_frame() range containment."""

    def test_both_range_ends_are_inclusive(self) -> None:
        """``start <= frame <= stop`` — both boundaries belong to the job.

        Probing only the interior of a range leaves either comparison free to
        become strict, which orphans the last frame of every job and sends its
        issues nowhere.
        """
        jobs = [RawJob(id=1, start_frame=0, stop_frame=9)]

        assert find_job_for_frame(jobs, 0) == 1
        assert find_job_for_frame(jobs, 9) == 1
        assert find_job_for_frame(jobs, 10) is None

    def test_first_matching_job_wins(self) -> None:
        jobs = [
            RawJob(id=1, start_frame=0, stop_frame=9),
            RawJob(id=2, start_frame=10, stop_frame=19),
        ]

        assert find_job_for_frame(jobs, 10) == 2
        assert find_job_for_frame(jobs, 20) is None


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

    def test_skipped_rows_do_not_stop_the_scan(self) -> None:
        """Every skip branch must ``continue`` rather than abandon the scan.

        A ``break`` in any of the three would silently drop the task's
        remaining issues after the first bad row.
        """
        incomplete = self._row("a.jpg")
        incomplete["bbox_y_br"] = None
        rows = [
            self._row("unknown.jpg"),
            incomplete,
            self._row("unmapped.jpg"),
            self._row("a.jpg"),
        ]
        # The job covers frame 3 but not the frame "unmapped.jpg" sits on.
        jobs = [RawJob(id=7, start_frame=3, stop_frame=3)]

        result = build_task_issues(
            pd.DataFrame(rows), {"a.jpg": 3, "unmapped.jpg": 50}, jobs
        )

        assert len(result.issues) == 1
        assert result.unknown_images == ["unknown.jpg"]
        assert result.missing_bbox == ["a.jpg"]
        assert result.unmapped_frames == ["unmapped.jpg"]


class TestTaskToRecords:
    """Tests for task_to_records() DTO -> domain record assembly."""

    @staticmethod
    def _meta_with_deleted() -> RawDataMeta:
        """Two known frames; deleted ids include one with no metadata at all."""
        return RawDataMeta(
            frames=[
                RawFrame(name="kept.jpg", width=640, height=480),
                RawFrame(name="gone.jpg", width=800, height=600),
            ],
            deleted_frames=[1, 99],
        )

    def test_each_frame_carries_its_own_jobs_position(self) -> None:
        """Frames split across two jobs must not share one review position.

        A task partway through review has one job accepted and another
        still being annotated; the records of each frame report the job
        that actually owns it.
        """
        task = make_task(5, subset="train", updated="2026-02-02")
        meta = RawDataMeta(
            frames=[
                RawFrame(name="done.jpg", width=10, height=20),
                RawFrame(name="doing.jpg", width=10, height=20),
            ],
        )
        jobs = [
            RawJob(
                id=1, start_frame=0, stop_frame=0, stage="acceptance", state="completed"
            ),
            RawJob(id=2, start_frame=1, stop_frame=1, stage="annotation", state="new"),
        ]

        records, _deleted = task_to_records(
            task, meta, RawAnnotations(), {}, {}, None, jobs
        )

        positions = {r.image_name: (r.job_stage, r.job_state) for r in records}
        assert positions == {
            "done.jpg": ("acceptance", "completed"),
            "doing.jpg": ("annotation", "new"),
        }

    def test_a_frame_no_job_covers_reports_an_empty_position(self) -> None:
        """An uncovered frame reads as empty, never as a finished job."""
        task = make_task(5, subset="train", updated="2026-02-02")
        meta = RawDataMeta(frames=[RawFrame(name="orphan.jpg", width=10, height=20)])

        records, _deleted = task_to_records(
            task, meta, RawAnnotations(), {}, {}, None, []
        )

        assert [(r.job_stage, r.job_state) for r in records] == [("", "")]

    def test_deleted_frames_carry_their_jobs_position(self) -> None:
        """A deleted frame keeps the review position of the job it belonged to.

        The partition folds deletion records back in to decide whether a
        task is finished, so a deleted frame that loses its job position
        would let an unfinished task pass as complete.
        """
        task = make_task(3, subset="train", updated="2026-02-02")
        jobs = [
            RawJob(id=1, start_frame=0, stop_frame=99, stage="annotation", state="new")
        ]

        _records, deleted = task_to_records(
            task, self._meta_with_deleted(), RawAnnotations(), {}, {}, None, jobs
        )

        assert [(d.job_stage, d.job_state) for d in deleted] == [
            ("annotation", "new"),
            ("annotation", "new"),
        ]

    def test_deleted_frames_carry_task_provenance(self) -> None:
        task = make_task(3, status="completed", subset="train", updated="2026-02-02")

        _records, deleted = task_to_records(
            task, self._meta_with_deleted(), RawAnnotations(), {}, {}
        )

        assert deleted == [
            DeletedImage(
                task_id=3,
                task_name="task-3",
                task_updated_date="2026-02-02",
                frame_id=1,
                image_name="gone.jpg",
                image_width=800,
                image_height=600,
                subset="train",
            ),
            DeletedImage(
                task_id=3,
                task_name="task-3",
                task_updated_date="2026-02-02",
                frame_id=99,
                image_name="<unknown>",
                image_width=0,
                image_height=0,
                subset="train",
            ),
        ]

    def test_unannotated_frames_default_to_blank_issue_fields(self) -> None:
        """A frame with no issue must yield empty strings, not placeholders.

        ``ctx.frame_issues.get(fid, ("", ""))`` supplies them, and the default
        is only observable on a frame that has no issue at all.
        """
        task = make_task(1, subset="val")
        meta = RawDataMeta(frames=[RawFrame(name="plain.jpg", width=10, height=20)])

        records, _deleted = task_to_records(task, meta, RawAnnotations(), {}, {})

        assert records == [
            ImageWithoutAnnotations(
                image_name="plain.jpg",
                image_width=10,
                image_height=20,
                task_id=1,
                task_name="task-1",
                task_updated_date="2026-01-01T00:00:00+00:00",
                frame_id=0,
                subset="val",
                issue_text="",
                issue_state="",
            )
        ]

    def test_unannotated_frame_keeps_its_issue(self) -> None:
        task = make_task(1)
        meta = RawDataMeta(frames=[RawFrame(name="plain.jpg", width=10, height=20)])
        issues = [RawIssue(id=5, frame=0, resolved=False, comments=["look here"])]

        records, _deleted = task_to_records(
            task, meta, RawAnnotations(), {}, {}, issues
        )

        assert records[0].issue_text == "look here"
        assert records[0].issue_state == "open"

    def test_attribute_names_reach_the_annotations(self) -> None:
        """attr_names must be forwarded, not dropped on the way to the shapes."""
        task = make_task(1)
        meta = RawDataMeta(frames=[RawFrame(name="a.jpg", width=10, height=20)])
        shape = make_raw_shape(attributes=[RawAttribute(spec_id=10, value="red")])

        records, _deleted = task_to_records(
            task, meta, RawAnnotations(shapes=[shape]), {1: "car"}, {10: "color"}
        )

        annotation = records[0]
        assert isinstance(annotation, BBoxAnnotation)
        assert annotation.attributes == {"color": "red"}

    def test_deleted_and_annotated_frames_are_not_reported_as_empty(self) -> None:
        task = make_task(1)
        meta = RawDataMeta(
            frames=[
                RawFrame(name="annotated.jpg", width=10, height=20),
                RawFrame(name="deleted.jpg", width=10, height=20),
                RawFrame(name="empty.jpg", width=10, height=20),
            ],
            deleted_frames=[1],
        )
        shape = make_raw_shape(frame=0, label_id=1)

        records, _deleted = task_to_records(
            task, meta, RawAnnotations(shapes=[shape]), {1: "car"}, {}
        )

        without = [r for r in records if isinstance(r, ImageWithoutAnnotations)]
        assert [r.image_name for r in without] == ["empty.jpg"]

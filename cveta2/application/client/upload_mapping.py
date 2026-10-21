"""Pure upload shape/issue construction and recovery issue matching."""

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd

from cveta2.application.ports.dtos import NewIssue, NewShape
from cveta2.domain.upload import BBOX_COLUMNS

if TYPE_CHECKING:
    from collections.abc import Hashable, Mapping

    from cveta2.application.ports.dtos import RawIssue, RawJob

_ISSUE_COLUMNS = frozenset({"issue_state", "issue_text"})


def find_job_for_frame(jobs: "list[RawJob]", frame: int) -> int | None:
    """Return the job ID whose [start_frame, stop_frame] range contains *frame*."""
    for job in jobs:
        if job.start_frame <= frame <= job.stop_frame:
            return job.id
    return None


def issue_position_from_row(row: "Mapping[Hashable, Any]") -> list[float] | None:
    """Return the row's bbox as an issue rectangle, or None without full bbox."""
    coords: list[float] = []
    for col in BBOX_COLUMNS:
        value = row.get(col)
        if value is None or pd.isna(value):
            return None
        coords.append(float(value))
    return coords


@dataclass
class ShapeBuildResult:
    """Shapes to upload plus per-reason skip diagnostics."""

    shapes: list[NewShape] = field(default_factory=list)
    unknown_images: int = 0
    unknown_labels: list[str] = field(default_factory=list)


def build_upload_shapes(
    annotations_df: pd.DataFrame,
    name_to_frame: dict[str, int],
    label_name_to_id: dict[str, int],
) -> ShapeBuildResult:
    """Translate annotated rows into ``NewShape`` DTOs (pure).

    Rows whose image is absent from *name_to_frame* or whose label is
    unknown are counted/collected in the returned result instead of being
    uploaded.
    """
    has_annotation = annotations_df["instance_label"].notna() & annotations_df[
        list(BBOX_COLUMNS)
    ].notna().all(axis=1)
    result = ShapeBuildResult()
    for row in annotations_df[has_annotation].to_dict("records"):
        img_name = str(row["image_name"])
        label_name = str(row["instance_label"])
        if img_name not in name_to_frame:
            result.unknown_images += 1
            continue
        if label_name not in label_name_to_id:
            result.unknown_labels.append(label_name)
            continue
        result.shapes.append(
            NewShape(
                frame=name_to_frame[img_name],
                label_id=label_name_to_id[label_name],
                points=[float(row[col]) for col in BBOX_COLUMNS],
            ),
        )
    return result


@dataclass
class IssueBuildResult:
    """Issues to open plus per-reason skip diagnostics (image names)."""

    issues: list[NewIssue] = field(default_factory=list)
    unknown_images: list[str] = field(default_factory=list)
    unmapped_frames: list[str] = field(default_factory=list)
    missing_bbox: list[str] = field(default_factory=list)


def build_task_issues(
    new_rows: pd.DataFrame,
    name_to_frame: dict[str, int],
    jobs: "list[RawJob]",
) -> IssueBuildResult:
    """Translate ``issue_state == "new"`` rows into ``NewIssue`` DTOs (pure).

    Rows with an unknown image, no job for the frame, or an incomplete
    bbox are recorded in the returned result rather than opened.
    """
    result = IssueBuildResult()
    for row in new_rows.to_dict("records"):
        image_name = str(row["image_name"])
        frame = name_to_frame.get(image_name)
        if frame is None:
            result.unknown_images.append(image_name)
            continue
        position = issue_position_from_row(row)
        if position is None:
            result.missing_bbox.append(image_name)
            continue
        job_id = find_job_for_frame(jobs, frame)
        if job_id is None:
            result.unmapped_frames.append(image_name)
            continue
        result.issues.append(
            NewIssue(
                job_id=job_id,
                frame=frame,
                position=position,
                message=str(row["issue_text"]),
            ),
        )
    return result


def _select_new_issue_rows(annotations_df: pd.DataFrame) -> pd.DataFrame:
    """Return deduplicated rows with ``issue_state == "new"`` and non-empty text.

    Issues are attached per-bbox, so the dedup key includes the bbox
    coordinates: distinct boxes on one image with the same text each keep
    their row; only fully identical duplicates collapse.
    """
    if not _ISSUE_COLUMNS.issubset(annotations_df.columns):
        return pd.DataFrame()
    df = annotations_df.copy()
    for column in _ISSUE_COLUMNS:
        df[column] = df[column].fillna("").astype(str).str.strip()
    new_rows: pd.DataFrame = df[(df["issue_state"] == "new") & (df["issue_text"] != "")]
    dedup_key = ["image_name", "issue_text"] + [
        col for col in BBOX_COLUMNS if col in new_rows.columns
    ]
    deduped: pd.DataFrame = new_rows.drop_duplicates(subset=dedup_key)
    return deduped


def _issues_not_yet_on_task(
    existing: "list[RawIssue]",
    built: "list[NewIssue]",
) -> "list[NewIssue]":
    """Drop the built issues a previous run already opened on the task.

    Match the frame, initial message and bbox. Coordinates tolerate a small
    round-trip error; each existing issue satisfies only one requested issue.
    """
    positions: dict[tuple[int, str], list[list[float]]] = {}
    for stored in existing:
        if stored.comments:
            positions.setdefault((stored.frame, stored.comments[0]), []).append(
                stored.position
            )
    pending: list[NewIssue] = []
    for issue in built:
        candidates = positions.get((issue.frame, issue.message), [])
        match = next(
            (
                index
                for index, position in enumerate(candidates)
                if len(position) == len(issue.position)
                and all(
                    math.isclose(a, b, rel_tol=0, abs_tol=1e-5)
                    for a, b in zip(position, issue.position, strict=True)
                )
            ),
            None,
        )
        if match is None:
            pending.append(issue)
        else:
            candidates.pop(match)
    return pending

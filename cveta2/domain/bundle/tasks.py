"""Pure task completion and supersession policy over original fetch evidence."""

from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from cveta2.domain.bundle.models import FetchTables, TaskManifest, UploadError
from cveta2.domain.verification.cells import explicitly_true, integer, is_missing, number


@dataclass(frozen=True)
class _Evidence:
    task_id: int
    image: str
    completed: bool
    deleted: bool
    explicitly_completed: bool


def _task_id(value: object) -> int:
    parsed = number(value)
    if parsed is None or not integer(value) or parsed < 0:
        raise UploadError(f"Invalid task_id in fetch evidence: {value!r}")
    # Decimal preserves lexical integers beyond binary floating-point precision.
    return int(Decimal(str(value)))


def _finished(explicit: object, stage: object, state: object) -> bool:
    if is_missing(explicit):
        return isinstance(stage, str) and stage == "acceptance" and isinstance(state, str) and state == "completed"
    if isinstance(explicit, (bool, np.bool_)):
        return bool(explicit)
    if isinstance(explicit, str):
        return explicit.casefold() == "true"
    return False


def _evidence(frame: pd.DataFrame, *, deleted: bool = False) -> list[_Evidence]:
    if frame.empty:
        return []
    required = {"task_id", "image_name"}
    missing = required - set(frame.columns)
    if missing:
        raise UploadError(f"Fetch evidence lacks required columns: {sorted(missing)}")
    evidence: list[_Evidence] = []
    for row in frame.to_dict(orient="records"):
        image = row["image_name"]
        if not isinstance(image, str) or not image:
            raise UploadError("Fetch evidence image_name must be a nonempty string")
        evidence.append(
            _Evidence(
                _task_id(row["task_id"]),
                image,
                _finished(
                    row.get("task_completed"),
                    row.get("job_stage"),
                    row.get("job_state"),
                ),
                deleted,
                explicitly_true(row.get("task_completed")),
            )
        )
    return evidence


def _without_deletion_markers(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop the reopen markers of ``in_progress.csv``: completed ``deleted`` rows.

    The completed deletion of a reopened image only marks it for ``merge`` and
    must not change which tasks a bundle lists. A pending deletion stays: it
    is evidence that its task is still open, the only such evidence when it
    comes from an older cveta2 without ``task_completed``.
    """
    if not {"instance_shape", "task_completed"}.issubset(frame.columns):
        return frame
    marker = (frame["instance_shape"] == "deleted") & frame["task_completed"].map(explicitly_true)
    return frame[~marker]


@dataclass(frozen=True)
class TracedTasks:
    """The task manifest of traceable rows and the count of rows it could not trace."""

    manifest: TaskManifest
    untraced_rows: int


def _traced_pairs(frame: pd.DataFrame) -> list[tuple[int, str] | None]:
    """Parse each row's ``(task_id, image_name)``; ``None`` for a missing or invalid one."""
    if "task_id" not in frame or "image_name" not in frame:
        return [None] * len(frame)
    pairs: list[tuple[int, str] | None] = []
    for task, image in zip(frame["task_id"].tolist(), frame["image_name"].tolist(), strict=True):
        try:
            task_id = _task_id(task)
        except UploadError:
            pairs.append(None)
            continue
        pairs.append((task_id, image) if isinstance(image, str) and image else None)
    return pairs


def derive_tasks(tables: FetchTables, clean: pd.DataFrame) -> TaskManifest:
    """List tasks of ``clean``, raising when a row does not trace to ``dataset.csv``."""
    traced = trace_tasks(tables, clean)
    if traced.untraced_rows:
        raise UploadError("Clean task/image pairs must originate in dataset.csv")
    return traced.manifest


def trace_tasks(tables: FetchTables, frame: pd.DataFrame) -> TracedTasks:
    """List retained tasks and fully superseded completed tasks.

    A row of ``frame`` is traceable when its ``task_id`` is a valid ID and its
    ``(task_id, image_name)`` pair is in the source ``dataset.csv``; other rows
    are counted in ``untraced_rows``, never raised on. The fetch evidence
    itself stays strict.

    Explicit completion describes every live job; absent completion falls back to
    legacy acceptance/completed rows. Any unfinished or unknown evidence excludes
    the entire task. Higher completed annotations and higher deletions supersede
    images independently of subsequent validation rejection.
    """
    dataset = _evidence(tables.dataset)
    in_progress = _evidence(_without_deletion_markers(tables.in_progress))
    evidence = [
        *dataset,
        *_evidence(tables.obsolete),
        *in_progress,
        *_evidence(tables.deleted, deleted=True),
    ]
    completed = {row.task_id for row in evidence if row.completed}
    completed.difference_update(row.task_id for row in evidence if not row.completed)
    # Explicit completion describes every live job of the task, so such a row is
    # a completed task's annotation waiting on a newer unfinished task. Rows
    # without it keep the conservative rule: in_progress.csv may hold a task
    # whose unfinished job left no other evidence.
    completed.difference_update(row.task_id for row in in_progress if not row.explicitly_completed)
    represented: dict[int, set[str]] = {}
    latest: dict[str, int] = {}
    for row in evidence:
        represented.setdefault(row.task_id, set()).add(row.image)
        if row.deleted or row.task_id in completed:
            latest[row.image] = max(latest.get(row.image, -1), row.task_id)
    source_pairs = {(row.task_id, row.image) for row in dataset}
    pairs = _traced_pairs(frame)
    traced = [pair for pair in pairs if pair is not None and pair in source_pairs]
    included = sorted({task_id for task_id, _image in traced})
    obsolete = sorted(
        task
        for task in completed
        if task not in included and all(latest.get(image, -1) > task for image in represented[task])
    )
    return TracedTasks(TaskManifest(included=included, obsolete=obsolete), len(pairs) - len(traced))

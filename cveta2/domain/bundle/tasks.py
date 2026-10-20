"""Pure task completion and supersession policy over original fetch evidence."""

from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from cveta2.domain.bundle.models import FetchTables, TaskManifest, UploadError
from cveta2.domain.verification.cells import integer, is_missing, number


@dataclass(frozen=True)
class _Evidence:
    task_id: int
    image: str
    completed: bool
    deleted: bool


def _task_id(value: object) -> int:
    parsed = number(value)
    if parsed is None or not integer(value) or parsed < 0:
        raise UploadError(f"Invalid task_id in fetch evidence: {value!r}")
    # Decimal preserves lexical integers beyond binary floating-point precision.
    return int(Decimal(str(value)))


def _finished(explicit: object, stage: object, state: object) -> bool:
    if is_missing(explicit):
        return (
            isinstance(stage, str)
            and stage == "acceptance"
            and isinstance(state, str)
            and state == "completed"
        )
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
            )
        )
    return evidence


def derive_tasks(tables: FetchTables, clean: pd.DataFrame) -> TaskManifest:
    """List retained tasks and fully superseded completed tasks.

    Explicit completion describes every live job; absent completion falls back to
    legacy acceptance/completed rows. Any unfinished or unknown evidence excludes
    the entire task. Higher completed annotations and higher deletions supersede
    images independently of subsequent validation rejection.
    """
    dataset = _evidence(tables.dataset)
    in_progress = _evidence(tables.in_progress)
    evidence = [
        *dataset,
        *_evidence(tables.obsolete),
        *in_progress,
        *_evidence(tables.deleted, deleted=True),
    ]
    completed = {row.task_id for row in evidence if row.completed}
    completed.difference_update(row.task_id for row in evidence if not row.completed)
    completed.difference_update(row.task_id for row in in_progress)
    represented: dict[int, set[str]] = {}
    latest: dict[str, int] = {}
    for row in evidence:
        represented.setdefault(row.task_id, set()).add(row.image)
        if row.deleted or row.task_id in completed:
            latest[row.image] = max(latest.get(row.image, -1), row.task_id)
    clean_rows = _evidence(clean)
    source_pairs = {(row.task_id, row.image) for row in dataset}
    if any((row.task_id, row.image) not in source_pairs for row in clean_rows):
        raise UploadError("Clean task/image pairs must originate in dataset.csv")
    included = sorted({row.task_id for row in clean_rows})
    obsolete = sorted(
        task
        for task in completed
        if task not in included
        and all(latest.get(image, -1) > task for image in represented[task])
    )
    return TaskManifest(included=included, obsolete=obsolete)

"""CVAT source metadata and full original task capture for managed datasets."""

import hashlib
import json

import pandas as pd

from cveta2.application.ports.cvat import CvatApiPort
from cveta2.application.ports.managed_sources import ProjectState, TaskAssembler
from cveta2.domain.managed.models import ManagedError, TaskSnapshot
from cveta2.domain.models import CSV_COLUMNS, LabelInfo, TaskInfo


class CvatSources:
    """Read existing API DTOs without leaking SDK types into managed workflows."""

    def __init__(self, api: CvatApiPort, assembler: TaskAssembler) -> None:
        """Receive an already scoped API connection from composition."""
        self._api = api
        self._assembler = assembler
        self._labels: dict[int, list[LabelInfo]] = {}
        self._tasks: dict[tuple[int, int], TaskInfo] = {}

    def inspect_project(self, project_id: int) -> ProjectState:
        """List live metadata and labels, without reading any annotations."""
        labels = self._api.get_project_labels(project_id)
        tasks = self._api.get_project_tasks(project_id)
        self._labels[project_id] = labels
        snapshots = []
        for task in tasks:
            if task.project_id != project_id:
                raise ManagedError(f"CVAT returned task {task.id} outside project {project_id}")
            self._tasks[project_id, task.id] = task
            jobs = self._api.get_task_jobs(task.id)
            completed = (
                task.status == "completed"
                and bool(jobs)
                and all(job.stage == "acceptance" and job.state == "completed" for job in jobs)
            )
            snapshots.append(
                TaskSnapshot(
                    id=task.id,
                    updated_date=task.updated_date,
                    completed=completed,
                )
            )
        label_data = [label.model_dump(mode="json") for label in sorted(labels, key=lambda item: item.id)]
        return ProjectState(
            tasks=snapshots,
            labels_fingerprint=hashlib.sha256(
                json.dumps(label_data, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
        )

    def read_task(self, project_id: int, task: TaskSnapshot) -> TaskSnapshot:
        """Capture annotations, deletions, jobs and issues as complete task evidence."""
        task_info = self._tasks.get((project_id, task.id))
        if task_info is None or project_id not in self._labels:
            raise ManagedError("Inspect the CVAT project before reading its tasks")
        labels = self._labels[project_id]
        label_names = {label.id: label.name for label in labels}
        attr_names = {attribute.id: attribute.name for label in labels for attribute in label.attributes}
        data = self._api.get_task_data_meta(task.id)
        annotations = self._api.get_task_annotations(task.id)
        jobs = self._api.get_task_jobs(task.id)
        issues = self._api.get_task_issues(task.id)
        records, deleted = self._assembler(
            task_info,
            data,
            annotations,
            label_names,
            attr_names,
            issues,
            jobs,
        )
        current = self._api.get_task(task.id)
        if current.project_id != project_id or current.updated_date != task.updated_date:
            raise ManagedError(f"CVAT task changed during capture: {project_id}/{task.id}")
        columns = list(CSV_COLUMNS)
        empty = pd.DataFrame(columns=columns).to_csv(index=False, lineterminator="\n")
        tables = {
            "dataset.csv": pd.DataFrame([record.to_csv_row() for record in records], columns=columns).to_csv(
                index=False, lineterminator="\n"
            ),
            "obsolete.csv": empty,
            "in_progress.csv": empty,
            "deleted.csv": pd.DataFrame([record.to_csv_row() for record in deleted], columns=columns).to_csv(
                index=False, lineterminator="\n"
            ),
        }
        completed = (
            current.status == "completed"
            and bool(jobs)
            and all(job.stage == "acceptance" and job.state == "completed" for job in jobs)
        )
        if completed != task.completed:
            raise ManagedError(f"CVAT task completion changed during capture: {task.id}")
        return TaskSnapshot(
            id=task.id,
            updated_date=task.updated_date,
            completed=completed,
            tables=tables,
        )

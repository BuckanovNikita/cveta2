"""Create marked CVAT frame issues while attesting annotation freshness."""

import hashlib
import json
import re
from dataclasses import asdict

from cveta2.application.ports.cvat import CvatApiPort
from cveta2.application.ports.dtos import NewIssue
from cveta2.application.ports.managed_feedback import FeedbackTaskState
from cveta2.domain.managed.models import ManagedError
from cveta2.domain.managed.preparation import FeedbackFinding
from cveta2.domain.models import TaskInfo


def _marker(finding: FeedbackFinding) -> str:
    digest = finding.marker.removeprefix("cveta2:verification:")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ManagedError("Invalid owned CVAT feedback marker")
    return f"[cveta2:verification:{digest}]"


class CvatFeedback:
    """Own only issue API writes; never update labels, annotations or job state."""

    def __init__(self, api: CvatApiPort) -> None:
        """Receive the existing, already scoped API connection."""
        self._api = api

    def _task(self, finding: FeedbackFinding) -> TaskInfo:
        _marker(finding)
        task = self._api.get_task(finding.task_id)
        if task.project_id != finding.project_id or task.id != finding.task_id:
            raise ManagedError("Feedback task no longer belongs to its source project")
        if finding.frame_id < 0:
            raise ManagedError("Feedback frame must be nonnegative")
        return task

    def inspect(self, finding: FeedbackFinding) -> FeedbackTaskState:
        """Fingerprint task/data/annotations/jobs/labels while excluding issues."""
        task = self._task(finding)
        annotations = self._api.get_task_annotations(task.id)
        data = self._api.get_task_data_meta(task.id)
        if finding.frame_id >= len(data.frames):
            raise ManagedError("Feedback frame is outside its original CVAT task")
        jobs = self._api.get_task_jobs(task.id)
        labels = self._api.get_project_labels(finding.project_id)
        after = self._task(finding)
        if after.updated_date != task.updated_date or after != task:
            raise ManagedError("CVAT task changed while checking feedback prerequisites")
        payload = {
            "task": task.model_dump(mode="json", exclude={"updated_date"}),
            "data": asdict(data),
            "annotations": [asdict(shape) for shape in sorted(annotations.shapes, key=lambda item: item.id)],
            "jobs": [asdict(job) for job in sorted(jobs, key=lambda item: item.id)],
            "labels": [label.model_dump(mode="json") for label in sorted(labels, key=lambda item: item.id)],
        }
        return FeedbackTaskState(
            project_id=finding.project_id,
            task_id=task.id,
            updated_date=task.updated_date,
            fingerprint=hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        )

    def issue_exists(self, finding: FeedbackFinding) -> bool:
        """Require the owned marker on the requested frame."""
        self._task(finding)
        token = _marker(finding)
        return any(
            issue.frame == finding.frame_id and any(token in message for message in issue.comments)
            for issue in self._api.get_task_issues(finding.task_id)
        )

    def create_issue(self, finding: FeedbackFinding) -> None:
        """Open a frame-level issue on its unique regular annotation job."""
        self._task(finding)
        jobs = [
            job
            for job in self._api.get_task_jobs(finding.task_id)
            if job.type == "annotation" and job.start_frame <= finding.frame_id <= job.stop_frame
        ]
        if len(jobs) != 1:
            raise ManagedError("Feedback frame has no unique annotation job")
        message = "\n".join(
            [
                _marker(finding),
                f"cveta2 dataset verification: {', '.join(finding.codes)}",
                *finding.messages,
            ]
        )
        self._api.create_issue(
            NewIssue(
                job_id=jobs[0].id,
                frame=finding.frame_id,
                position=[0.0, 0.0],
                message=message,
            )
        )

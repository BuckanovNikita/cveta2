"""Review feedback is idempotent, resumable and never masks annotation edits."""

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from cveta2.adapters.cvat.managed_feedback import CvatFeedback
from cveta2.adapters.files.managed_feedback import LocalFeedbackLedger
from cveta2.application.ports.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawIssue,
    RawJob,
)
from cveta2.application.ports.managed_feedback import FeedbackTaskState
from cveta2.application.use_cases.managed_feedback import (
    reconcile_pending,
    report_findings,
)
from cveta2.domain.managed.models import (
    ManagedError,
    ManagedSnapshot,
    SourceSnapshot,
    TaskSnapshot,
)
from cveta2.domain.managed.preparation import FeedbackFinding
from cveta2.domain.models import LabelInfo, TaskInfo


def _finding(task: int = 1, frame: int = 0) -> FeedbackFinding:
    marker = hashlib.sha256(f"main/{task}/{frame}/invalid_bbox".encode()).hexdigest()
    return FeedbackFinding(
        source_id="main",
        project_id=12,
        task_id=task,
        frame_id=frame,
        codes=["invalid_bbox"],
        messages=["Invalid training box"],
        marker=marker,
    )


def _snapshot() -> ManagedSnapshot:
    return ManagedSnapshot(
        definition_hash="definition",
        registry_hash="registry",
        sources=[
            SourceSnapshot(
                name="main",
                type="cvat",
                project_id=12,
                tasks={"1": TaskSnapshot(id=1, updated_date="0", completed=True)},
            )
        ],
    )


class _Remote:
    def __init__(self, ledger: LocalFeedbackLedger) -> None:
        self.ledger = ledger
        self.issues: set[str] = set()
        self.states = {task: FeedbackTaskState(12, task, "0", "annotations-v1") for task in (1, 2)}
        self.creates = 0
        self.fail_before: set[int] = set()
        self.fail_after: set[int] = set()
        self.edit_during: set[int] = set()
        self.bump_time = True

    def inspect(self, finding: FeedbackFinding) -> FeedbackTaskState:
        return self.states[finding.task_id]

    def issue_exists(self, finding: FeedbackFinding) -> bool:
        return finding.marker in self.issues

    def create_issue(self, finding: FeedbackFinding) -> None:
        receipt = self.ledger.get_receipt(finding.marker)
        assert receipt is not None
        assert not receipt.delivered
        if finding.task_id in self.fail_before:
            raise ManagedError("CVAT unavailable")
        self.creates += 1
        self.issues.add(finding.marker)
        current = self.states[finding.task_id]
        self.states[finding.task_id] = FeedbackTaskState(
            12,
            finding.task_id,
            str(int(current.updated_date) + 1) if self.bump_time else current.updated_date,
            "annotations-v2" if finding.task_id in self.edit_during else current.fingerprint,
        )
        if finding.task_id in self.fail_after:
            raise ManagedError("Uncertain create response")


def test_feedback_retries_and_timestamp_chain_are_idempotent(tmp_path: Path) -> None:
    ledger = LocalFeedbackLedger(tmp_path)
    remote = _Remote(ledger)
    findings = [_finding(frame=0), _finding(frame=1)]
    outcome = report_findings(findings, remote=remote, ledger=ledger, unmapped=3)
    assert outcome.created == 2
    assert outcome.existing == 0
    assert not outcome.failed
    assert outcome.unmapped == 3
    assert remote.creates == 2
    effective = ledger.effective_snapshot(_snapshot())
    assert effective.sources[0].tasks["1"].updated_date == "2"
    assert _snapshot().sources[0].tasks["1"].updated_date == "0"
    repeated = report_findings(findings, remote=remote, ledger=ledger)
    assert repeated.existing == 2
    assert not repeated.failed
    assert remote.creates == 2


def test_issue_writes_without_timestamp_changes_do_not_conflict(tmp_path: Path) -> None:
    ledger = LocalFeedbackLedger(tmp_path)
    remote = _Remote(ledger)
    remote.bump_time = False
    outcome = report_findings([_finding(frame=0), _finding(frame=1)], remote=remote, ledger=ledger)
    assert outcome.created == 2
    assert not outcome.failed
    assert ledger.effective_snapshot(_snapshot()).sources[0].tasks["1"].updated_date == "0"


def test_uncertain_create_recovers_by_reads_before_freshness_validation(
    tmp_path: Path,
) -> None:
    ledger = LocalFeedbackLedger(tmp_path)
    remote = _Remote(ledger)
    remote.fail_after.add(1)
    finding = _finding()
    outcome = report_findings([finding], remote=remote, ledger=ledger)
    assert len(outcome.failed) == 1
    assert outcome.created == 0
    receipt = ledger.get_receipt(finding.marker)
    assert receipt is not None
    assert not receipt.delivered
    assert ledger.effective_snapshot(_snapshot()).sources[0].tasks["1"].updated_date == "0"
    reconcile_pending([finding], remote=remote, ledger=ledger)
    assert ledger.effective_snapshot(_snapshot()).sources[0].tasks["1"].updated_date == "1"
    assert remote.creates == 1
    assert report_findings([finding], remote=remote, ledger=ledger).existing == 1


def test_real_annotation_change_is_never_acknowledged(tmp_path: Path) -> None:
    ledger = LocalFeedbackLedger(tmp_path)
    remote = _Remote(ledger)
    remote.edit_during.add(1)
    finding = _finding()
    outcome = report_findings([finding], remote=remote, ledger=ledger)
    assert len(outcome.failed) == 1
    assert ledger.effective_snapshot(_snapshot()).sources[0].tasks["1"].updated_date == "0"
    with pytest.raises(ManagedError, match="annotations changed"):
        reconcile_pending([finding], remote=remote, ledger=ledger)


def test_partial_failure_is_explicit_and_other_findings_complete(
    tmp_path: Path,
) -> None:
    ledger = LocalFeedbackLedger(tmp_path)
    remote = _Remote(ledger)
    remote.fail_before.add(1)
    outcome = report_findings([_finding(1), _finding(2)], remote=remote, ledger=ledger)
    assert outcome.created == 1
    assert len(outcome.failed) == 1
    remote.fail_before.clear()
    retried = report_findings([_finding(1), _finding(2)], remote=remote, ledger=ledger)
    assert retried.created == 1
    assert retried.existing == 1
    assert not retried.failed


def test_new_finding_cannot_hide_edit_between_same_task_deliveries(
    tmp_path: Path,
) -> None:
    ledger = LocalFeedbackLedger(tmp_path)
    remote = _Remote(ledger)
    assert not report_findings([_finding()], remote=remote, ledger=ledger).failed
    remote.states[1] = FeedbackTaskState(12, 1, "2", "annotations-v2")
    outcome = report_findings([_finding(frame=1)], remote=remote, ledger=ledger)
    assert len(outcome.failed) == 1
    assert remote.creates == 1
    assert ledger.effective_snapshot(_snapshot()).sources[0].tasks["1"].updated_date == "1"


def test_preexisting_marker_does_not_create_an_issue(tmp_path: Path) -> None:
    ledger = LocalFeedbackLedger(tmp_path)
    remote = _Remote(ledger)
    finding = _finding()
    remote.issues.add(finding.marker)
    outcome = report_findings([finding], remote=remote, ledger=ledger)
    assert outcome.existing == 1
    assert remote.creates == 0
    assert not outcome.failed


def test_checkpoint_failure_prevents_remote_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = LocalFeedbackLedger(tmp_path)
    remote = _Remote(ledger)

    def fail_save(_ledger: object) -> None:
        raise ManagedError("disk full")

    monkeypatch.setattr(ledger, "_save", fail_save)
    outcome = report_findings([_finding()], remote=remote, ledger=ledger)
    assert len(outcome.failed) == 1
    assert remote.creates == 0


def test_corrupt_or_symlinked_ledger_fails_closed(tmp_path: Path) -> None:
    ledger = LocalFeedbackLedger(tmp_path)
    path = tmp_path / "feedback.json"
    path.write_text('{"format_version":1,"receipts":{},"receipts":{}}')
    with pytest.raises(ManagedError, match="Duplicate"):
        ledger.get_receipt(_finding().marker)
    path.unlink()
    path.symlink_to(tmp_path / "absent.json")
    with pytest.raises(ManagedError, match="nonsymlink"):
        ledger.get_receipt(_finding().marker)


def _api() -> Mock:
    api = Mock()
    api.get_task.return_value = TaskInfo(
        id=1,
        name="task",
        project_id=12,
        status="completed",
        subset="",
        updated_date="now",
    )
    api.get_task_annotations.return_value = RawAnnotations()
    api.get_task_data_meta.return_value = RawDataMeta([RawFrame("image.jpg", 100, 100)])
    api.get_task_jobs.return_value = [
        RawJob(
            id=7,
            start_frame=0,
            stop_frame=0,
            stage="acceptance",
            state="completed",
        )
    ]
    api.get_project_labels.return_value = [LabelInfo(id=3, name="cat")]
    api.get_task_issues.return_value = []
    return api


def test_cvat_adapter_writes_only_a_frame_issue_and_checks_ownership() -> None:
    api = _api()
    remote = CvatFeedback(api)
    finding = _finding()
    before = remote.inspect(finding)
    remote.create_issue(finding)
    request = api.create_issue.call_args.args[0]
    assert request.job_id == 7
    assert request.frame == 0
    assert request.position == [0.0, 0.0]
    assert finding.marker in request.message
    assert not remote.issue_exists(finding)
    api.get_task_issues.return_value = [
        RawIssue(
            id=8,
            frame=0,
            resolved=False,
            comments=[request.message],
        )
    ]
    assert remote.issue_exists(finding)
    assert remote.inspect(finding).fingerprint == before.fingerprint
    canonical = finding.model_copy(
        update={
            "marker": f"cveta2:verification:{finding.marker}",
        }
    )
    assert canonical.marker in request.message
    assert remote.issue_exists(canonical)
    api.patch_task_annotations.assert_not_called()
    api.patch_job.assert_not_called()
    api.get_task.return_value = api.get_task.return_value.model_copy(update={"project_id": 99})
    with pytest.raises(ManagedError, match="source project"):
        remote.create_issue(finding)


def test_cvat_adapter_rejects_ambiguous_jobs_and_wrong_frame_marker() -> None:
    api = _api()
    finding = _finding()
    remote = CvatFeedback(api)
    api.get_task_jobs.return_value *= 2
    with pytest.raises(ManagedError, match="unique annotation job"):
        remote.create_issue(finding)
    api.get_task_issues.return_value = [
        RawIssue(
            id=8,
            frame=1,
            resolved=False,
            comments=[f"[cveta2-dataset:{finding.marker}]"],
        )
    ]
    assert not remote.issue_exists(finding)

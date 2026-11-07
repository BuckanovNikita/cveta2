"""Resumable frame feedback with explicit failures and issue-only freshness."""

from cveta2.application.ports.managed_feedback import (
    CvatFeedback,
    FeedbackLedger,
    FeedbackReceipt,
    FeedbackTaskState,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.managed.models import ManagedError
from cveta2.domain.managed.preparation import FeedbackFinding, FeedbackOutcome


def _receipt_matches(receipt: FeedbackReceipt, finding: FeedbackFinding) -> bool:
    return (
        receipt.source_id == finding.source_id
        and receipt.project_id == finding.project_id
        and receipt.task_id == finding.task_id
        and receipt.frame_id == finding.frame_id
        and receipt.marker == finding.marker
    )


def _same_facts(before: FeedbackTaskState, after: FeedbackTaskState) -> bool:
    return (
        before.project_id == after.project_id
        and before.task_id == after.task_id
        and before.fingerprint == after.fingerprint
    )


def reconcile_pending(findings: list[FeedbackFinding], *, remote: CvatFeedback, ledger: FeedbackLedger) -> None:
    """Acknowledge uncertain own writes by reads only, before freshness checks.

    A marker and unchanged annotation-relevant facts are both required. Mere
    existence of an older CVAT issue cannot excuse an unrelated task edit.
    """
    for finding in findings:
        receipt = ledger.get_receipt(finding.marker)
        if receipt is None or receipt.delivered:
            continue
        if not _receipt_matches(receipt, finding):
            raise ManagedError("Feedback marker belongs to different source evidence")
        state = remote.inspect(finding)
        if state.fingerprint != receipt.fingerprint:
            raise ManagedError(f"Source annotations changed during feedback: {finding.task_id}")
        if remote.issue_exists(finding):
            ledger.complete(finding, state)


def _known_delivery(
    receipt: FeedbackReceipt | None,
    finding: FeedbackFinding,
    before: FeedbackTaskState,
    remote: CvatFeedback,
) -> bool:
    """Validate a prior checkpoint and recognize already delivered findings."""
    if receipt is None:
        return False
    if not _receipt_matches(receipt, finding):
        raise ManagedError("Feedback marker belongs to different source evidence")
    if receipt.fingerprint != before.fingerprint:
        raise ManagedError(f"Source annotations changed during feedback: {finding.task_id}")
    if receipt.delivered:
        if not remote.issue_exists(finding):
            raise ManagedError("Previously acknowledged CVAT issue disappeared; prepare again")
        # Later findings on this same task may have advanced its time. Do not
        # widen this receipt to acknowledge any unrelated timestamp changes.
        return True
    if before.updated_date != receipt.before_date and not remote.issue_exists(finding):
        raise ManagedError(f"Unacknowledged task change during feedback: {finding.task_id}")
    return False


def _deliver(finding: FeedbackFinding, *, remote: CvatFeedback, ledger: FeedbackLedger) -> bool:
    """Return True for a new issue and False for an already-present marker."""
    before = remote.inspect(finding)
    receipt = ledger.get_receipt(finding.marker)
    if _known_delivery(receipt, finding, before, remote):
        return False
    if remote.issue_exists(finding):
        if receipt is None:
            ledger.begin(finding, before)
        ledger.complete(finding, before)
        return False
    if receipt is None:
        ledger.begin(finding, before)
    remote.create_issue(finding)
    after = remote.inspect(finding)
    if not _same_facts(before, after):
        raise ManagedError(f"Source annotations changed while reporting task {finding.task_id}")
    if not remote.issue_exists(finding):
        raise ManagedError(f"Created CVAT issue was not confirmed for task {finding.task_id}")
    ledger.complete(finding, after)
    return True


def report_findings(
    findings: list[FeedbackFinding],
    *,
    remote: CvatFeedback,
    ledger: FeedbackLedger,
    unmapped: int = 0,
) -> FeedbackOutcome:
    """Deliver every mapped finding, preserving pending checkpoints on failure."""
    created = 0
    existing = 0
    failed = []
    for finding in findings:
        try:
            was_created = _deliver(finding, remote=remote, ledger=ledger)
        except Cveta2Error as error:
            failed.append(f"{finding.source_id}/{finding.task_id}/{finding.frame_id}: {error}")
            continue
        created += int(was_created)
        existing += int(not was_created)
    return FeedbackOutcome(created=created, existing=existing, unmapped=unmapped, failed=failed)

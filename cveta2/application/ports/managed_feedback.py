"""Typed CVAT review feedback and durable retry acknowledgement effects."""

from dataclasses import dataclass
from typing import Protocol

from cveta2.domain.managed.models import ManagedSnapshot
from cveta2.domain.managed.preparation import FeedbackFinding


@dataclass(frozen=True)
class FeedbackTaskState:
    """Annotation-relevant facts exclude issue text and mutable update time."""

    project_id: int
    task_id: int
    updated_date: str
    fingerprint: str


@dataclass(frozen=True)
class FeedbackReceipt:
    """An owned marker's before/after state, persisted before remote mutation."""

    source_id: str
    project_id: int
    task_id: int
    frame_id: int
    marker: str
    before_date: str
    fingerprint: str
    after_date: str | None = None
    delivered: bool = False


class CvatFeedback(Protocol):
    """Read source-frame ownership and write only a deduplicated review issue."""

    def inspect(self, finding: FeedbackFinding) -> FeedbackTaskState:
        """Validate source ownership and fingerprint annotations/data/jobs/labels."""
        ...

    def issue_exists(self, finding: FeedbackFinding) -> bool:
        """Check the exact frame and owned marker on existing issue comments."""
        ...

    def create_issue(self, finding: FeedbackFinding) -> None:
        """Create one marked review issue without changing annotations/status."""
        ...


class FeedbackLedger(Protocol):
    """Keep delivery state outside the immutable preparation payload."""

    def get_receipt(self, marker: str) -> FeedbackReceipt | None:
        """Return a durable owned attempt, or None before its first write."""
        ...

    def begin(self, finding: FeedbackFinding, state: FeedbackTaskState) -> None:
        """Persist a pending checkpoint before the first remote create."""
        ...

    def complete(self, finding: FeedbackFinding, state: FeedbackTaskState) -> None:
        """Acknowledge a verified issue-only timestamp transition."""
        ...

    def effective_snapshot(self, snapshot: ManagedSnapshot) -> ManagedSnapshot:
        """Apply only acknowledged own-write timestamp transitions."""
        ...

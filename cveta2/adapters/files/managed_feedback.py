"""Atomic local feedback receipts, separate from immutable prepared payloads."""

import json
import os
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import Field, ValidationError

from cveta2.application.ports.managed_feedback import FeedbackReceipt, FeedbackTaskState
from cveta2.domain.managed.models import ManagedError, ManagedSnapshot, StrictModel
from cveta2.domain.managed.preparation import FeedbackFinding


class _StoredReceipt(StrictModel):
    source_id: str
    project_id: int
    task_id: int
    frame_id: int
    marker: str
    before_date: str
    fingerprint: str
    after_date: str | None = None
    delivered: bool = False


class _Ledger(StrictModel):
    format_version: Literal[1] = 1
    receipts: dict[str, _StoredReceipt] = Field(default_factory=dict)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManagedError(f"Duplicate feedback ledger key: {key}")
        result[key] = value
    return result


class LocalFeedbackLedger:
    """Persist intent before a remote issue write and acknowledge it afterward."""

    def __init__(self, directory: Path) -> None:
        """Use one preparation-owned delivery file, never a public payload file."""
        self._path = directory / "feedback.json"

    def _load(self) -> _Ledger:
        if self._path.is_symlink():
            raise ManagedError("Feedback ledger must be a regular nonsymlink file")
        if not self._path.exists():
            return _Ledger()
        if not self._path.is_file():
            raise ManagedError("Feedback ledger must be a regular nonsymlink file")
        try:
            ledger = _Ledger.model_validate(
                json.loads(
                    self._path.read_text(encoding="utf-8"),
                    object_pairs_hook=_unique_pairs,
                )
            )
        except (OSError, json.JSONDecodeError, UnicodeError, ValidationError) as error:
            raise ManagedError("Cannot read feedback delivery ledger") from error
        if any(marker != receipt.marker for marker, receipt in ledger.receipts.items()):
            raise ManagedError("Feedback ledger index does not match its receipt")
        return ledger

    def _save(self, ledger: _Ledger) -> None:
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                prefix=".cveta2-feedback-",
                dir=self._path.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(ledger.model_dump_json(indent=2).encode())
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self._path)
        except OSError as error:
            raise ManagedError("Cannot persist required feedback checkpoint") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def get_receipt(self, marker: str) -> FeedbackReceipt | None:
        """Return the exact durable intent, rejecting mismatched index keys."""
        stored = self._load().receipts.get(marker)
        if stored is None:
            return None
        if stored.marker != marker:
            raise ManagedError("Feedback ledger index does not match its receipt")
        return FeedbackReceipt(**stored.model_dump())

    def begin(self, finding: FeedbackFinding, state: FeedbackTaskState) -> None:
        """Persist the checkpoint before permitting a remote issue write."""
        ledger = self._load()
        if finding.marker in ledger.receipts:
            return
        if any(
            receipt.source_id == finding.source_id
            and receipt.project_id == finding.project_id
            and receipt.task_id == finding.task_id
            and receipt.fingerprint != state.fingerprint
            for receipt in ledger.receipts.values()
        ):
            raise ManagedError("Source annotations changed between feedback findings")
        receipt = FeedbackReceipt(
            source_id=finding.source_id,
            project_id=finding.project_id,
            task_id=finding.task_id,
            frame_id=finding.frame_id,
            marker=finding.marker,
            before_date=state.updated_date,
            fingerprint=state.fingerprint,
        )
        ledger.receipts[finding.marker] = _StoredReceipt.model_validate(asdict(receipt))
        self._save(ledger)

    def complete(self, finding: FeedbackFinding, state: FeedbackTaskState) -> None:
        """Only unchanged source facts can acknowledge an owned write's time."""
        ledger = self._load()
        stored = ledger.receipts.get(finding.marker)
        if stored is None or stored.fingerprint != state.fingerprint:
            raise ManagedError("Cannot acknowledge feedback without matching source facts")
        if (
            stored.source_id != finding.source_id
            or stored.project_id != state.project_id
            or stored.task_id != state.task_id
            or stored.frame_id != finding.frame_id
        ):
            raise ManagedError("Feedback acknowledgement has conflicting source ownership")
        ledger.receipts[finding.marker] = stored.model_copy(
            update={
                "after_date": state.updated_date,
                "delivered": True,
            }
        )
        self._save(ledger)

    def effective_snapshot(self, snapshot: ManagedSnapshot) -> ManagedSnapshot:
        """Chain acknowledged issue-only times without rewriting source records."""
        receipts = self._load().receipts.values()
        sources = []
        for source in snapshot.sources:
            tasks = dict(source.tasks)
            for task_key, task in source.tasks.items():
                updated = task.updated_date
                transitions = [
                    receipt
                    for receipt in receipts
                    if receipt.delivered
                    and receipt.source_id == source.name
                    and receipt.project_id == source.project_id
                    and receipt.task_id == task.id
                    and receipt.after_date is not None
                    and receipt.after_date != receipt.before_date
                ]
                visited = {updated}
                for _ in transitions:
                    matching = [receipt for receipt in transitions if receipt.before_date == updated]
                    if not matching:
                        break
                    dates = {receipt.after_date for receipt in matching}
                    if len(dates) != 1:
                        raise ManagedError("Ambiguous feedback timestamp acknowledgements")
                    after = matching[0].after_date
                    if after is None or after in visited:
                        break
                    visited.add(after)
                    updated = after
                tasks[task_key] = task.model_copy(update={"updated_date": updated})
            sources.append(source.model_copy(update={"tasks": tasks}))
        return snapshot.model_copy(update={"sources": sources})

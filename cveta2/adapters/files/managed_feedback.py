"""Atomic local feedback receipts, kept apart from the prepared payload files."""

import json
import os
import re
from collections.abc import Iterable
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


def _acknowledged_chain(
    receipts: Iterable[_StoredReceipt],
    owner: tuple[str, int, int],
    start: str,
    fingerprint: str | None = None,
) -> list[str]:
    """Follow acknowledged issue-only time transitions of one task from ``start``."""
    transitions = [
        receipt
        for receipt in receipts
        if receipt.delivered
        and (receipt.source_id, receipt.project_id, receipt.task_id) == owner
        and (fingerprint is None or receipt.fingerprint == fingerprint)
        and receipt.after_date is not None
        and receipt.after_date != receipt.before_date
    ]
    chain = [start]
    for _ in transitions:
        matching = [receipt for receipt in transitions if receipt.before_date == chain[-1]]
        if not matching:
            break
        dates = {receipt.after_date for receipt in matching}
        if len(dates) != 1:
            raise ManagedError("Ambiguous feedback timestamp acknowledgements")
        after = matching[0].after_date
        if after is None or after in chain:
            break
        chain.append(after)
    return chain


def shared_ledger_path(root: Path, source_hash: str) -> Path:
    """Locate the ledger shared by every preparation of one fetched source snapshot."""
    if re.fullmatch(r"[0-9a-f]{64}", source_hash) is None:
        raise ManagedError("Invalid source snapshot hash for the feedback ledger")
    return root / f"{source_hash}.json"


def _read_ledger(path: Path) -> _Ledger:
    if path.is_symlink():
        raise ManagedError("Feedback ledger must be a regular nonsymlink file")
    if not path.exists():
        return _Ledger()
    if not path.is_file():
        raise ManagedError("Feedback ledger must be a regular nonsymlink file")
    try:
        ledger = _Ledger.model_validate(
            json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_pairs,
            )
        )
    except (OSError, json.JSONDecodeError, UnicodeError, ValidationError) as error:
        raise ManagedError("Cannot read feedback delivery ledger") from error
    if any(marker != receipt.marker for marker, receipt in ledger.receipts.items()):
        raise ManagedError("Feedback ledger index does not match its receipt")
    return ledger


class LocalFeedbackLedger:
    """Persist intent before a remote issue write and acknowledge it afterward."""

    def __init__(self, directory: Path, shared: Path | None = None) -> None:
        """Keep receipts outside public payload files.

        ``shared`` is the ledger of every preparation built from one fetch, so
        each sees the others' acknowledged issue times. A preparation's own
        ``feedback.json`` from before sharing is preserved and its missing
        receipts are migrated to ``shared`` when read.
        """
        self._local = directory / "feedback.json"
        self._path = shared or self._local

    def _load(self) -> _Ledger:
        ledger = _read_ledger(self._path)
        if self._path != self._local:
            missing = {
                marker: receipt
                for marker, receipt in _read_ledger(self._local).receipts.items()
                if marker not in ledger.receipts
            }
            if missing:
                ledger.receipts.update(missing)
                self._save(ledger)
        return ledger

    def _save(self, ledger: _Ledger) -> None:
        temporary: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
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

    def rebase(self, finding: FeedbackFinding, state: FeedbackTaskState) -> bool:
        """Rebase a pending receipt only along its own task's acknowledged chain."""
        ledger = self._load()
        stored = ledger.receipts.get(finding.marker)
        if stored is None or stored.delivered or stored.fingerprint != state.fingerprint:
            return False
        owner = (stored.source_id, stored.project_id, stored.task_id)
        if owner != (finding.source_id, state.project_id, state.task_id):
            return False
        chain = _acknowledged_chain(ledger.receipts.values(), owner, stored.before_date, stored.fingerprint)
        if len(chain) == 1 or state.updated_date != chain[-1]:
            return False
        ledger.receipts[finding.marker] = stored.model_copy(update={"before_date": state.updated_date})
        self._save(ledger)
        return True

    def effective_snapshot(self, snapshot: ManagedSnapshot) -> ManagedSnapshot:
        """Chain acknowledged issue-only times without rewriting source records."""
        receipts = self._load().receipts.values()
        sources = []
        for source in snapshot.sources:
            tasks = dict(source.tasks)
            for task_key, task in source.tasks.items():
                if source.project_id is None:
                    continue
                owner = (source.name, source.project_id, task.id)
                updated = _acknowledged_chain(receipts, owner, task.updated_date)[-1]
                tasks[task_key] = task.model_copy(update={"updated_date": updated})
            sources.append(source.model_copy(update={"tasks": tasks}))
        return snapshot.model_copy(update={"sources": sources})

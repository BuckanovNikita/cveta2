"""Preparation record and review feedback contracts for managed datasets."""

from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue

from cveta2.domain.managed.models import StrictModel


class FeedbackFinding(StrictModel):
    """A frame-level finding already traced to original CVAT evidence."""

    source_id: str
    project_id: int
    task_id: int
    frame_id: int
    codes: list[str]
    messages: list[str]
    marker: str


class ManagedRecord(StrictModel):
    """Plain state of one managed preparation; it holds no checksum.

    ``parent_id`` and ``parent_version`` are the latest finalized version when the
    sources were fetched. It is the parent that publication links, except for a
    ``first`` version, which starts a lineage: publication links no parent, and the
    recorded version only proves that nothing newer appeared since. ``ready`` is
    informational: it says the payload was written.
    """

    format_version: Literal[3] = 3
    name: str
    parent_id: str | None
    parent_version: str | None = None
    findings: list[FeedbackFinding] = Field(default_factory=list)
    ready: bool
    clean: bool = True
    first: bool = False


class FeedbackOutcome(StrictModel):
    """Honest delivery accounting including local/unmapped diagnostics.

    ``skipped`` counts findings not delivered because their task changed after fetch.
    """

    created: int = 0
    existing: int = 0
    unmapped: int = 0
    failed: list[str] = Field(default_factory=list)
    skipped: int = 0


class PreparationSummary(StrictModel):
    """Prompt-free local preparation result."""

    directory: Path
    ready: bool
    report: dict[str, JsonValue]

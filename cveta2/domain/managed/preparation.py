"""Immutable preparation and review feedback contracts for managed datasets."""

from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue

from cveta2.domain.managed.models import ManagedSnapshot, StrictModel


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
    """Version-two local binding; delivery state lives outside immutable inputs."""

    format_version: Literal[2] = 2
    name: str
    definition_hash: str
    parent_id: str | None
    parent_version: str | None = None
    registry_hash: str
    source_hash: str
    input_hash: str
    payload_hashes: dict[str, str]
    image_hashes: dict[str, str]
    snapshot: ManagedSnapshot
    findings: list[FeedbackFinding] = Field(default_factory=list)
    ready: bool
    clean: bool = False


class FeedbackOutcome(StrictModel):
    """Honest delivery accounting including local/unmapped diagnostics."""

    created: int = 0
    existing: int = 0
    unmapped: int = 0
    failed: list[str] = Field(default_factory=list)


class PreparationSummary(StrictModel):
    """Prompt-free local preparation result."""

    directory: Path
    ready: bool
    report: dict[str, JsonValue]

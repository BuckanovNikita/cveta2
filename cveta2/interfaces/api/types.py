"""Stable public connection settings and workflow result models."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from cveta2.composition.client import CvatClient
from cveta2.domain.models import TaskInfo

CacheMode = Literal["use", "refresh", "off"]
"""Task-annotation cache modes for :func:`fetch` / :func:`fetch_task`."""


@dataclass(frozen=True, slots=True)
class Connection:
    """Explicit CVAT connection settings for the public API.

    All fields are optional; missing values resolve from environment
    variables, the config file and the built-in preset (explicit > env >
    file > preset).  ``client`` injects a ready client (tests /
    connection reuse): it must be already entered, or constructed with a
    fake ``api=``; it is neither entered nor closed here.
    """

    host: str | None = None
    username: str | None = None
    password: str | None = None
    organization: str | None = None
    config_path: Path | None = None
    client: CvatClient | None = None


class UploadResult(BaseModel):
    """Summary of a completed upload."""

    task_id: int
    task_name: str
    url: str
    images: int
    deleted: int
    annotations: int
    issues: int


class WhatsNewResult(BaseModel):
    """Completed tasks a fetched dataset CSV does not account for."""

    tasks: list[TaskInfo]
    cutoff: int

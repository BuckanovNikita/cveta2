"""Versioned neutral contracts for shared configuration and source evidence."""

import hashlib
import json
import re
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from cveta2.domain.errors import Cveta2Error

_SPLIT_TOLERANCE = 1e-9


class ManagedError(Cveta2Error):
    """A managed definition, source, preparation or feedback cannot proceed."""


class MigrationRequired(ManagedError):  # noqa: N818 - actionable migration contract.
    """Legacy settings need user-reviewed separation before use."""


class StrictModel(BaseModel):
    """Reject misspelled contract fields instead of silently losing policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CvatIdentity(StrictModel):
    """One shared CVAT server and optional organization."""

    host: str = Field(min_length=1)
    organization: str | None = None

    @field_validator("organization")
    @classmethod
    def personal_workspace(cls, value: str | None) -> str | None:
        """Treat empty CVAT organization slugs and null as the personal workspace."""
        return value or None

    @field_validator("host")
    @classmethod
    def public_host(cls, value: str) -> str:
        """Keep credentials out of the shared server identity."""
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError("CVAT host must be HTTP(S) without credentials")
        return value.rstrip("/")


class ProjectDefinition(StrictModel):
    """Shared project identity and source interpretation, without local paths."""

    id: int = Field(ge=0)
    name: str = ""
    sync_root: str | None = None
    ignored_prefix: str | None = None
    task_cache_s3: str | None = None
    ignore: list[dict[str, JsonValue]] = Field(default_factory=list)

    @field_validator("ignore")
    @classmethod
    def ignored_tasks(
        cls, values: list[dict[str, JsonValue]]
    ) -> list[dict[str, JsonValue]]:
        """Validate shared exclusion records before any source is contacted."""
        for entry in values:
            task_id = entry.get("id")
            if (
                set(entry) - {"id", "name", "description", "silent"}
                or isinstance(task_id, bool)
                or not isinstance(task_id, int)
                or task_id < 0
                or any(
                    not isinstance(entry[key], str)
                    for key in ("name", "description")
                    if key in entry
                )
                or ("silent" in entry and not isinstance(entry["silent"], bool))
            ):
                raise ValueError("Invalid shared ignored-task record")
        return values


class SourceDefinition(StrictModel):
    """A safe local source name and exactly one remote source reference."""

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    type: Literal["cvat", "s3-csv"]
    project: str | None = None
    uri: str | None = None

    @model_validator(mode="after")
    def source_reference(self) -> Self:
        """Reject ambiguous source types and unsafe S3 object references."""
        if self.type == "cvat":
            if not self.project or self.uri is not None:
                raise ValueError("CVAT source requires only a project reference")
        else:
            parts = urlsplit(self.uri or "")
            if (
                self.project is not None
                or parts.scheme != "s3"
                or not parts.netloc
                or any(c in parts.netloc for c in "@: \\")
                or parts.query
                or parts.fragment
                or not parts.path.endswith(".csv")
                or "\x00" in (self.uri or "")
                or any(
                    p in {"", ".", ".."}
                    for p in parts.path.removeprefix("/").split("/")
                )
            ):
                raise ValueError("S3 source requires an exact s3://bucket/key.csv URI")
        return self


class ClearMLDestination(StrictModel):
    """Exact project and dataset name; no recursive project matching."""

    project: str = Field(min_length=1)
    dataset: str = Field(min_length=1)


class SplitPolicy(StrictModel):
    """Stable hash targets; published assignments are never rebalanced."""

    train: float = Field(default=0.6, ge=0, le=1)
    val: float = Field(default=0.2, ge=0, le=1)
    test: float = Field(default=0.2, ge=0, le=1)
    seed: int = 42

    @model_validator(mode="after")
    def total(self) -> Self:
        """Require a complete probability distribution and usable train/val."""
        if (
            abs(self.train + self.val + self.test - 1) > _SPLIT_TOLERANCE
            or not self.train
            or not self.val
        ):
            raise ValueError("Splits must sum to one with positive train and val")
        return self


class OverlapDecision(StrictModel):
    """Choose one source or exclude content; bind to exact participating sources."""

    source: str | None = None
    members: list[str]


class DatasetDefinition(StrictModel):
    """All portable policy needed to assemble one managed dataset."""

    sources: list[SourceDefinition] = Field(min_length=1)
    clearml: ClearMLDestination
    api_url: str = Field(min_length=1)
    s3_roots: list[str] = Field(default_factory=list)
    empty_classes: list[int] = Field(default_factory=list)
    splits: SplitPolicy = Field(default_factory=SplitPolicy)
    overlaps: dict[str, OverlapDecision] = Field(default_factory=dict)

    @field_validator("api_url")
    @classmethod
    def public_class_api(cls, value: str) -> str:
        """Do not permit credential-bearing endpoints in portable policy."""
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError("Class API must be HTTP(S) without embedded credentials")
        return value

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        """One identity contributes once, even if given a second alias."""
        names = [s.name for s in self.sources]
        refs = [(s.type, s.project, s.uri) for s in self.sources]
        if len(set(names)) != len(names) or len(set(refs)) != len(refs):
            raise ValueError("Dataset source names and references must be unique")
        return self


class ProjectConfig(StrictModel):
    """Authoritative shared configuration, never merged with personal policy."""

    schema_version: Literal[1] = 1
    cvat: CvatIdentity
    projects: dict[str, ProjectDefinition] = Field(default_factory=dict)
    datasets: dict[str, DatasetDefinition] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references(self) -> Self:
        """Reject unknown project references and duplicate destination pairs."""
        destinations = [
            (d.clearml.project, d.clearml.dataset) for d in self.datasets.values()
        ]
        if len(destinations) != len(set(destinations)):
            raise ValueError("ClearML destination pairs must be unique")
        ids = [p.id for p in self.projects.values()]
        if len(ids) != len(set(ids)):
            raise ValueError("CVAT project identities must be unique")
        for key in (*self.projects, *self.datasets):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", key):
                raise ValueError("Project and dataset keys must be safe identifiers")
        for dataset in self.datasets.values():
            for source in dataset.sources:
                if source.type == "cvat" and source.project not in self.projects:
                    raise ValueError(f"Unknown shared project: {source.project}")
        return self


class TaskSnapshot(StrictModel):
    """Live freshness and original per-task evidence, including empty tasks."""

    id: int = Field(ge=0)
    updated_date: str
    completed: bool
    tables: dict[str, str] = Field(default_factory=dict)


class SourceSnapshot(StrictModel):
    """Source evidence before transformation or training filtering."""

    name: str
    type: Literal["cvat", "s3-csv"]
    project_id: int | None = None
    tasks: dict[str, TaskSnapshot] = Field(default_factory=dict)
    labels_fingerprint: str = ""
    tables: dict[str, str] = Field(default_factory=dict)
    uri: str | None = None
    content_hash: str | None = None
    etag: str | None = None
    version_id: str | None = None
    fetched: list[int] = Field(default_factory=list)
    reused: list[int] = Field(default_factory=list)


class ManagedSnapshot(StrictModel):
    """Complete source evidence stored inside the published tasks YAML."""

    format_version: Literal[1] = 1
    definition_hash: str
    registry_hash: str
    parent_id: str | None = None
    sources: list[SourceSnapshot]
    assignments: dict[str, Literal["train", "val", "test"]] = Field(
        default_factory=dict
    )
    image_hashes: dict[str, str] = Field(default_factory=dict)


class ManagedMetadata(StrictModel):
    """Portable resolved policy, not a reference to a personal configuration."""

    format_version: Literal[1] = 1
    name: str
    definition_hash: str
    definition: DatasetDefinition
    cvat: CvatIdentity
    assignments: dict[str, Literal["train", "val", "test"]] = Field(
        default_factory=dict
    )


def definition_fingerprint(config: ProjectConfig, name: str) -> str:
    """Bind only the chosen dataset and the project definitions it references."""
    try:
        definition = config.datasets[name]
    except KeyError as error:
        raise ManagedError(f"Unknown managed dataset: {name}") from error
    projects = {
        s.project: config.projects[s.project].model_dump(mode="json")
        for s in definition.sources
        if s.project is not None
    }
    content = {
        "cvat": config.cvat.model_dump(mode="json"),
        "dataset": definition.model_dump(mode="json"),
        "projects": projects,
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()

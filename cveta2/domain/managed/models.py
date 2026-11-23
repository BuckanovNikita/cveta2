"""Versioned neutral contracts for shared configuration and source evidence."""

import hashlib
import json
import re
from typing import Literal, Self, cast
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from cveta2.domain.class_registry import ApiClass
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import LabelInfo
from cveta2.domain.paths import parse_sync_root


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
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
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

    @field_validator("sync_root", "task_cache_s3")
    @classmethod
    def s3_root(cls, value: str | None) -> str | None:
        """Reject roots the S3 adapters cannot parse, before any command uses them."""
        if value is not None:
            try:
                parse_sync_root(value)
            except ValueError:
                # The parser's own message repeats the value; diagnostics must not.
                raise ValueError("Expected s3://bucket[/prefix] or a nonempty bare prefix") from None
        return value

    @field_validator("ignore")
    @classmethod
    def ignored_tasks(cls, values: list[dict[str, JsonValue]]) -> list[dict[str, JsonValue]]:
        """Validate shared exclusion records before any source is contacted."""
        for entry in values:
            task_id = entry.get("id")
            if (
                set(entry) - {"id", "name", "description", "silent"}
                or isinstance(task_id, bool)
                or not isinstance(task_id, int)
                or task_id < 0
                or any(not isinstance(entry[key], str) for key in ("name", "description") if key in entry)
                or ("silent" in entry and not isinstance(entry["silent"], bool))
            ):
                raise ValueError("Invalid shared ignored-task record")
        return values

    @property
    def ignored_task_ids(self) -> frozenset[int]:
        """Task ids excluded from every source; the validator guarantees integers."""
        return frozenset(cast("int", entry["id"]) for entry in self.ignore)


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
                or any(p in {"", ".", ".."} for p in parts.path.removeprefix("/").split("/"))
            ):
                raise ValueError("S3 source requires an exact s3://bucket/key.csv URI")
        return self


class ClearMLDestination(StrictModel):
    """Exact project and dataset name; no recursive project matching."""

    project: str = Field(min_length=1)
    dataset: str = Field(min_length=1)


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
    overlaps: dict[str, OverlapDecision] = Field(default_factory=dict)

    @field_validator("api_url")
    @classmethod
    def public_class_api(cls, value: str) -> str:
        """Do not permit credential-bearing endpoints in portable policy."""
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
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

    @model_validator(mode="before")
    @classmethod
    def reject_split_policy(cls, data: object) -> object:
        """Name a split policy left from cveta2 0.15 so the user deletes it."""
        if isinstance(data, dict) and isinstance(datasets := data.get("datasets"), dict):
            for name, dataset in datasets.items():
                if isinstance(dataset, dict) and "splits" in dataset:
                    raise ManagedError(
                        f"datasets.{name}.splits is no longer supported; delete the key from the shared "
                        "configuration: splits are not assigned automatically any more"
                    )
        return data

    @model_validator(mode="after")
    def references(self) -> Self:
        """Reject unknown project references and duplicate destination pairs."""
        destinations = [(d.clearml.project, d.clearml.dataset) for d in self.datasets.values()]
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
    labels: list[LabelInfo] | None = Field(default=None, exclude_if=lambda value: value is None)
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
    registry: list[ApiClass] | None = Field(default=None, exclude_if=lambda value: value is None)
    parent_id: str | None = None
    sources: list[SourceSnapshot]
    assignments: dict[str, Literal["train", "val", "test"]] = Field(default_factory=dict)
    image_hashes: dict[str, str] = Field(default_factory=dict)


class ManagedMetadata(StrictModel):
    """Portable resolved policy, not a reference to a personal configuration."""

    format_version: Literal[1] = 1
    name: str
    definition_hash: str
    definition: DatasetDefinition
    cvat: CvatIdentity
    assignments: dict[str, Literal["train", "val", "test"]] = Field(default_factory=dict)

    @field_validator("definition", mode="before")
    @classmethod
    def drop_legacy_splits(cls, value: object) -> object:
        """Read a definition published by cveta2 0.15, whose split policy no longer applies."""
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key != "splits"}
        return value


def dataset_definition(config: ProjectConfig, name: str) -> DatasetDefinition:
    """Resolve one named managed dataset or fail with an actionable error."""
    try:
        return config.datasets[name]
    except KeyError as error:
        raise ManagedError(f"Unknown managed dataset: {name}") from error


def _digest(content: object) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def source_fingerprint(config: ProjectConfig, definition: DatasetDefinition) -> str:
    """Bind a fetched snapshot to exactly what fetch read, independently of source order.

    Covers the CVAT server identity and, per source, its name, type, resolved
    CVAT project id with its ignored task ids, and S3 object URI. Project keys,
    display names, ignore bookkeeping (name, description, silent) and legacy
    image/cache settings do not change the captured evidence. Preparation and
    publication compare it to reject a snapshot fetched for another definition;
    fetch reuse is decided per source and does not depend on this hash while
    the previous CVAT identity is known.
    """
    sources: list[dict[str, object]] = []
    for source in sorted(definition.sources, key=lambda item: item.name):
        project = config.projects[source.project] if source.project is not None else None
        sources.append(
            {
                "name": source.name,
                "type": source.type,
                "project_id": project.id if project is not None else None,
                "ignored": sorted(project.ignored_task_ids) if project is not None else [],
                "uri": source.uri,
            }
        )
    return _digest({"cvat": config.cvat.model_dump(mode="json"), "sources": sources})


def definition_fingerprint(config: ProjectConfig, definition: DatasetDefinition) -> str:
    """Bind the source fingerprint and every policy prepare applies or publishes.

    Order-free lists are normalized, so reordering roots, classes or overlap
    members keeps a preparation publishable.
    """
    policy: dict[str, object] = {
        "source": source_fingerprint(config, definition),
        "clearml": definition.clearml.model_dump(mode="json"),
        "api_url": definition.api_url,
        "s3_roots": sorted(set(definition.s3_roots)),
        "empty_classes": sorted(set(definition.empty_classes)),
        "overlaps": {
            digest: {"source": decision.source, "members": sorted(decision.members)}
            for digest, decision in definition.overlaps.items()
        },
    }
    return _digest(policy)

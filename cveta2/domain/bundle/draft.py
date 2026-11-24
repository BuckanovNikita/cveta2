"""The editable dataset draft written by ``fetch`` and the resolution of preparation values."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from cveta2.domain.bundle.models import DatasetMetadata, ImageRoots
from cveta2.domain.bundle.preparation import PrepareOptions
from cveta2.domain.managed.models import PublicationSettings
from cveta2.domain.storage import CloudStorageInfo


class DraftDestination(BaseModel):
    """ClearML destination keys of a draft; any of them may be absent."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    project: str | None = Field(default=None, min_length=1)
    dataset: str | None = Field(default=None, min_length=1)
    output_uri: str | None = Field(default=None, min_length=1)


class DatasetDraft(BaseModel):
    """What ``fetch`` could prefill in ``dataset.yaml``; ``verify`` reads it as a default."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    clearml: DraftDestination | None = None
    api_url: str | None = Field(default=None, min_length=1)
    empty_classes: list[int] | None = None
    images: ImageRoots | None = None


def s3_root_of(storage: CloudStorageInfo) -> str:
    """Return the ``s3://`` root that covers the cloud storage's images."""
    prefix = storage.prefix.strip("/")
    return f"s3://{storage.bucket}/{prefix}" if prefix else f"s3://{storage.bucket}"


def build_draft(
    publication: PublicationSettings | None,
    storage: CloudStorageInfo | None,
    images_dir: Path | None,
) -> DatasetDraft:
    """Prefill a draft from the project's publication settings, its storage and the image directory."""
    project = dataset = output_uri = None
    if publication is not None:
        project = publication.clearml.project
        dataset = publication.clearml.dataset
        output_uri = publication.clearml.output_uri
    if output_uri is None and storage is not None:
        output_uri = f"s3://{storage.bucket}/.clearml"
    destination = DraftDestination(project=project, dataset=dataset, output_uri=output_uri)
    s3_roots: list[str] = []
    if publication is not None and publication.s3_roots is not None:
        s3_roots = list(publication.s3_roots)
    elif storage is not None:
        s3_roots = [s3_root_of(storage)]
    local_roots = [str(images_dir)] if images_dir is not None else []
    return DatasetDraft(
        clearml=destination if destination != DraftDestination() else None,
        api_url=publication.api_url if publication is not None else None,
        empty_classes=list(publication.empty_classes) if publication is not None else None,
        images=ImageRoots(local_root=local_roots, s3_root=s3_roots) if local_roots or s3_roots else None,
    )


@dataclass(frozen=True)
class ResolvedPreparation:
    """Every preparation value after applying flag > draft > parent."""

    project: str | None
    dataset_name: str | None
    output_uri: str | None
    api_url: str | None
    class_marks: dict[int, bool]
    local_roots: tuple[str, ...]
    parent_local_roots: tuple[str, ...]
    s3_roots: tuple[str, ...]


def resolve_preparation(
    options: PrepareOptions,
    draft: DatasetDraft | None,
    parent: DatasetMetadata | None,
) -> ResolvedPreparation:
    """Pick each value from the flag, else the draft, else (``api_url`` and roots only) the parent."""
    destination = draft.clearml if draft is not None else None
    draft_roots = draft.images if draft is not None and draft.images is not None else ImageRoots()
    parent_roots = parent.images if parent is not None else ImageRoots()
    marks = dict.fromkeys(draft.empty_classes or [], True) if draft is not None else {}
    marks.update(options.class_empty)
    return ResolvedPreparation(
        project=options.project or (destination.project if destination else None),
        dataset_name=options.dataset_name or (destination.dataset if destination else None),
        output_uri=options.output_uri or (destination.output_uri if destination else None),
        api_url=options.api_url
        or (draft.api_url if draft is not None else None)
        or (parent.api_url if parent is not None else None),
        class_marks=marks,
        local_roots=tuple(dict.fromkeys([*options.local_roots, *draft_roots.local_root])),
        parent_local_roots=tuple(parent_roots.local_root),
        s3_roots=tuple(dict.fromkeys([*parent_roots.s3_root, *draft_roots.s3_root, *options.s3_roots])),
    )

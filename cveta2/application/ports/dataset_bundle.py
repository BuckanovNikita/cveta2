"""Infrastructure contracts for explicit dataset preparation and publication."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from cveta2.application.ports.verification import MediaInspector
from cveta2.domain.bundle.draft import DatasetDraft
from cveta2.domain.bundle.models import (
    ApiClass,
    DatasetMetadata,
    DatasetParent,
    ImageRoots,
    Publication,
    TaskManifest,
)
from cveta2.domain.bundle.preparation import (
    BundleProposal,
    CurrentBundle,
    PreparedDataset,
    SourceSnapshot,
)
from cveta2.domain.managed.models import ClearMLDestination


class ClassApi(Protocol):
    """Load public class identities."""

    def fetch(self, url: str) -> list[ApiClass]:
        """Return validated records or raise UploadError."""
        ...


class DatasetStore(Protocol):
    """Inspect exact finalized datasets and publish a validated child."""

    def names(self, project: str) -> list[str]:
        """List dataset names within one exact project."""
        ...

    def latest(self, project: str, name: str) -> DatasetParent | None:
        """Return latest finalized nonarchived exact parent; errors are not absence."""
        ...

    def publish(  # noqa: PLR0913
        self,
        project: str,
        name: str,
        parent_id: str | None,
        directory: Path,
        *,
        files: tuple[str, ...],
        output_uri: str | None = None,
    ) -> Publication:
        """Publish only the listed files, reporting known child IDs on failure."""
        ...

    def parent_file(self, parent: DatasetParent, filename: str) -> Path | None:
        """Return a local copy of one file of that exact version, or None when it is not listed.

        SDK and download errors raise UploadError; they never mean "absent".
        """
        ...


class S3Storage(Protocol):
    """Prove access to configured storage roots."""

    def check_root(self, root: str) -> None:
        """Reject missing or inaccessible buckets/prefixes."""
        ...


class RootChecks(Protocol):
    """Check independent local and remote ancestry without guessing mappings."""

    def check_local_root(self, root: str) -> str:
        """Return a canonical existing directory."""
        ...

    def uncovered_paths(self, frame: pd.DataFrame, roots: ImageRoots) -> list[str]:
        """Return current source paths outside approved local roots."""
        ...

    def check_s3_paths(self, frame: pd.DataFrame, roots: ImageRoots) -> None:
        """Reject uncovered or ambiguous remote paths."""
        ...

    def missing_files(self, frame: pd.DataFrame) -> list[str]:
        """Return each distinct absolute ``image_path`` that is not a regular file, in row order."""
        ...


class DraftFiles(Protocol):
    """Read and write the editable ``dataset.yaml`` draft of a fetch directory."""

    def read_draft(self, directory: Path) -> DatasetDraft | None:
        """Return the draft, or None when the directory has no ``dataset.yaml``."""
        ...

    def write_draft(self, directory: Path, draft: DatasetDraft) -> bool:
        """Write the draft; return True when a different file was moved to ``dataset.yaml.bak``."""
        ...


class BundleFiles(DraftFiles, Protocol):
    """Read fetch sources, write prepared bundles and read their current files."""

    def read_source(self, directory: Path) -> SourceSnapshot:
        """Read all four source files exactly once and parse the captured bytes."""
        ...

    def read_metadata(self, path: Path) -> DatasetMetadata:
        """Read strict parent metadata."""
        ...

    def default_directory(self, source: Path) -> Path:
        """Return the first free sibling ``<source>-prepared``, ``<source>-prepared-2``, … of the resolved source."""
        ...

    def save_preparation(self, directory: Path, proposal: BundleProposal) -> PreparedDataset:
        """Write a new bundle in one step: the archive and report, and the payload when ready."""
        ...

    def read_bundle(self, directory: Path) -> CurrentBundle:
        """Read the bundle's current files once; a missing or malformed one raises UploadError."""
        ...

    def read_rows(self, path: Path) -> pd.DataFrame:
        """Read a downloaded parent ``dataset.csv`` strictly; errors raise UploadError naming the file."""
        ...

    def write_tasks(self, directory: Path, tasks: TaskManifest) -> None:
        """Rewrite the bundle's ``tasks.yaml``."""
        ...

    def stage_publication(self, bundle: CurrentBundle, tasks: TaskManifest) -> AbstractContextManager[Path]:
        """Hold the captured bytes and ``tasks.yaml`` in a private directory until publication ends."""
        ...

    def write_publication(self, directory: Path, publication: Publication, destination: ClearMLDestination) -> None:
        """Record the published version in the bundle's ``publication.json``; may raise OSError."""
        ...


@dataclass(frozen=True)
class BundleServices:
    """All effects required by the prompt-free bundle workflows."""

    api: ClassApi
    datasets: DatasetStore
    s3: S3Storage
    roots: RootChecks
    files: BundleFiles
    media: MediaInspector

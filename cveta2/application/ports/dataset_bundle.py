"""Infrastructure contracts for explicit dataset preparation and publication."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from cveta2.application.ports.verification import MediaInspector
from cveta2.domain.bundle.models import (
    ApiClass,
    DatasetMetadata,
    DatasetParent,
    ImageRoots,
    Publication,
    TaskManifest,
)
from cveta2.domain.bundle.preparation import (
    BundleDraft,
    PreparedDataset,
    SourceSnapshot,
    StoredBundle,
)


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

    def publish(
        self, project: str, name: str, parent_id: str | None, directory: Path
    ) -> Publication:
        """Publish only payload files, reporting known child IDs on failure."""
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


class BundleFiles(Protocol):
    """Capture and persist stable source/payload bytes behind a file boundary."""

    def read_source(self, directory: Path) -> SourceSnapshot:
        """Read all four source files exactly once and parse the captured bytes."""
        ...

    def read_metadata(self, path: Path) -> DatasetMetadata:
        """Read strict parent metadata."""
        ...

    def save_preparation(self, directory: Path, draft: BundleDraft) -> PreparedDataset:
        """Write a new local report and, when ready, immutable upload evidence."""
        ...

    def stage_prepared(self, directory: Path) -> AbstractContextManager[StoredBundle]:
        """Verify hashes and stage stable bytes; clean temporary files on exit."""
        ...

    def payload_matches(
        self, bundle: StoredBundle, frame: pd.DataFrame, tasks: TaskManifest
    ) -> bool:
        """Compare rederived publication bytes with the reviewed snapshot."""
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

"""Filesystem contract for task outputs and upload image lookup."""

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

import pandas as pd

from cveta2.domain.models import ProjectAnnotations, TaskAnnotations, TaskInfo
from cveta2.domain.partition import PartitionResult
from cveta2.domain.storage import CloudStorageInfo


class FetchFiles(Protocol):
    """Write fetch results and resolve fetched record locations."""

    def prepare_tasks(self, output_dir: Path) -> Path:
        """Create and return the task CSV output directory."""
        ...

    def write_task_csv(
        self, task: TaskInfo, result: TaskAnnotations, tasks_dir: Path
    ) -> None:
        """Write one nonempty task annotation CSV."""
        ...

    def cleanup_tasks(self, tasks_dir: Path) -> None:
        """Remove temporary task CSV outputs with best-effort cleanup."""
        ...

    def populate_record_paths(
        self,
        result: ProjectAnnotations,
        cs_info: CloudStorageInfo | None,
        images_dir: Path | None,
        ignored_prefix: str | None = None,
    ) -> None:
        """Populate downloaded image paths after annotation caching."""
        ...

    def write_raw_csv(self, result: ProjectAnnotations, output_dir: Path) -> None:
        """Write the optional unpartitioned fetch output."""
        ...

    def write_partition_csvs(
        self, partition: PartitionResult, output_dir: Path
    ) -> None:
        """Write all partition and deletion outputs."""
        ...

    def write_dataset_and_deleted(
        self, result: ProjectAnnotations, output_dir: Path
    ) -> None:
        """Write selected-task annotation and deletion outputs."""
        ...


class UploadFiles(Protocol):
    """Find and read local upload inputs without remote storage coupling."""

    def enrich_dataframe_paths(
        self,
        df: pd.DataFrame,
        cs_info: CloudStorageInfo,
        found_images: dict[str, Path],
        name_to_server_file: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        """Resolve local paths and add the intended remote frame paths."""
        ...

    def read_exclude_names(self, in_progress_path: str | None) -> set[str]:
        """Read excluded frame names from the optional CSV."""
        ...

    def resolve_images(
        self, image_names: Iterable[str], search_dirs: list[Path]
    ) -> tuple[dict[str, Path], list[str]]:
        """Find local named images in ordered search directories."""
        ...


class WorkflowFiles(FetchFiles, UploadFiles, Protocol):
    """Combined adapter interface for production workflow assembly."""

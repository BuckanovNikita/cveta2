"""Application-owned dataset persistence contract."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import pandas as pd

from cveta2.domain.models import ProjectAnnotations
from cveta2.domain.partition import PartitionResult
from cveta2.domain.storage import CloudStorageInfo


class DatasetFiles(Protocol):
    """Dataset workflow effects with explicit caller-owned paths."""

    def read_dataset_csv(
        self,
        path: Path,
        required_columns: set[str],
        *,
        require_task_id_column: bool = False,
    ) -> pd.DataFrame:
        """Read and validate a dataset CSV."""
        ...

    def populate_record_paths(
        self,
        result: ProjectAnnotations,
        cs_info: CloudStorageInfo | None,
        images_dir: Path | None,
        ignored_prefix: str | None = None,
    ) -> None:
        """Resolve annotation record paths against local images."""
        ...

    def enrich_dataframe_paths(
        self,
        df: pd.DataFrame,
        cs_info: CloudStorageInfo,
        found_images: dict[str, Path],
        name_to_server_file: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        """Add resolved image and server paths to a frame."""
        ...

    def save_csv(self, df: pd.DataFrame, path: Path) -> None:
        """Create parent directories and persist the frame."""
        ...

    def write_raw_csv(self, result: ProjectAnnotations, output_dir: Path) -> None:
        """Persist unpartitioned annotations and deleted images."""
        ...

    def write_partition_csvs(
        self, partition: PartitionResult, output_dir: Path
    ) -> None:
        """Persist all dataset partitions."""
        ...

    def write_dataset_and_deleted(
        self, result: ProjectAnnotations, output_dir: Path
    ) -> None:
        """Persist annotations and deleted images."""
        ...

    def read_deleted_names(self, path: Path | None) -> set[str]:
        """Read current CSV or legacy deleted-image names."""
        ...

    def read_baseline_siblings(self, path: Path) -> Sequence[pd.DataFrame]:
        """Read optional baseline CSVs with degradation reporting."""
        ...

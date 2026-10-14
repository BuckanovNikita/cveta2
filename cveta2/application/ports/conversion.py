"""Application-owned, workflow-specific conversion file effects."""

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from cveta2.application.ports.dataset import DatasetFiles
from cveta2.domain.conversion import ExportContext


class ConversionFiles(DatasetFiles, Protocol):
    """Image input discovery and conversion-owned output operations."""

    def resolve_images(
        self, image_names: Iterable[str], search_dirs: list[Path]
    ) -> tuple[dict[str, Path], list[str]]:
        """Find images in the supplied directories in order."""
        ...

    def find_image_by_stem(
        self, stem: str, search_dirs: list[Path], subdirs: list[str] | None = None
    ) -> Path | None:
        """Find an image by stem and conventional extensions."""
        ...

    def image_size(self, img_path: Path) -> tuple[int, int]:
        """Read image dimensions."""
        ...

    def write_conversion_csv(self, rows: list[dict[str, object]], path: Path) -> None:
        """Persist imported rows in canonical CSV column order."""
        ...

    def load_yaml(self, path: Path) -> object:
        """Read external dataset YAML."""
        ...

    def load_class_names(self, path: Path) -> dict[int, str]:
        """Read and validate a class-name YAML."""
        ...

    def resolve_dataset_root(self, yaml_path: Path, raw_root: object) -> Path:
        """Resolve a declared YOLO root relative to its YAML."""
        ...

    def split_images(self, raw_split: object, dataset_root: Path) -> list[Path]:
        """Enumerate declared split sources in declaration order."""
        ...

    def prune_yolo_output(self, ctx: ExportContext) -> None:
        """Remove obsolete conversion image and label files."""
        ...

    def coco_owned_paths(self, ctx: ExportContext) -> set[Path]:
        """Validate prior COCO inventory before any output changes."""
        ...

    def prune_coco_output(self, ctx: ExportContext, owned: set[Path]) -> None:
        """Remove obsolete files owned by a prior COCO export."""
        ...

    def prepare_yolo_output(self, output_dir: Path, splits: list[str]) -> None:
        """Create image and label directories for declared splits."""
        ...

    def prepare_coco_output(self, directory: Path) -> None:
        """Create the validated COCO output root even for an empty dataset."""
        ...

    def prepare_coco_split(self, directory: Path) -> None:
        """Create a COCO split directory."""
        ...

    def label_text(self, path: Path) -> str | None:
        """Read an existing label file, returning none when absent."""
        ...

    def materialize_image(self, src: Path, dst: Path, mode: str) -> None:
        """Place an image using the requested link or copy mode."""
        ...

    def write_output_text(self, path: Path, text: str) -> None:
        """Write conversion-owned text with pinned UTF-8 encoding."""
        ...

    def dataset_yaml_available(self, path: Path) -> bool:
        """Check whether the dataset YAML exists."""
        ...

    def image_available(self, path: Path) -> bool:
        """Check whether a declared image exists."""
        ...

    def prediction_labels(self, path: Path) -> list[Path]:
        """List prediction label files in deterministic order."""
        ...

    def resolved_output_dir(self, path: Path) -> Path:
        """Resolve the dataset root written to YOLO metadata."""
        ...

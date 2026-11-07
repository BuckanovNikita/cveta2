"""Prompt-free managed dataset API with explicit independent config selection."""

from pathlib import Path
from typing import Any

from cveta2.composition import managed
from cveta2.domain.bundle.models import Publication
from cveta2.domain.managed.preparation import FeedbackOutcome, PreparationSummary


def list_datasets(*, config_path: Path | None = None, project_config: Path | None = None) -> list[dict[str, Any]]:
    """List locally configured dataset mappings without network access."""
    return managed.list_datasets(config_path=config_path, project_config=project_config)


def show_dataset(name: str, *, config_path: Path | None = None, project_config: Path | None = None) -> dict[str, Any]:
    """Show resolved source policy and latest exact ClearML parent."""
    return managed.show_dataset(name, config_path=config_path, project_config=project_config)


def dataset_versions(
    name: str, *, config_path: Path | None = None, project_config: Path | None = None
) -> list[dict[str, str | None]]:
    """List finalized versions in the exact configured destination."""
    return managed.dataset_versions(name, config_path=config_path, project_config=project_config)


def fetch_dataset(
    name: str,
    *,
    output_dir: Path,
    refresh: bool = False,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> dict[str, Any]:
    """Fetch original mixed-source evidence for an external transformation."""
    return managed.fetch_dataset(
        name,
        output_dir=output_dir,
        refresh=refresh,
        config_path=config_path,
        project_config=project_config,
    )


def prepare_managed_dataset(  # noqa: PLR0913 - explicit public workflow inputs.
    name: str,
    csv: Path,
    *,
    source: Path,
    output_dir: Path,
    clean: bool = False,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> PreparationSummary:
    """Assign managed splits and verify arbitrary externally transformed rows."""
    return managed.prepare_managed_dataset(
        name,
        csv,
        source=source,
        output_dir=output_dir,
        clean=clean,
        config_path=config_path,
        project_config=project_config,
    )


def compare_datasets(
    old: str,
    new: str,
    *,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> dict[str, Any]:
    """Compare local candidates or immutable ClearML dataset identities."""
    return managed.compare_datasets(old, new, config_path=config_path, project_config=project_config)


def report_dataset_errors(
    prepared: Path,
    *,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> FeedbackOutcome:
    """Deliver only findings traced to original CVAT source frames."""
    return managed.report_dataset_errors(prepared, config_path=config_path, project_config=project_config)


def publish_dataset(
    prepared: Path,
    *,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> Publication:
    """Recheck and publish accepted data after traceable feedback completes."""
    return managed.publish_dataset(prepared, config_path=config_path, project_config=project_config)

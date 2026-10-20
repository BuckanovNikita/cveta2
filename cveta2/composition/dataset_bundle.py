"""Construct optional remote and local dependencies for explicit publication."""

from pathlib import Path

from cveta2.adapters.class_api.http import HttpClassApi
from cveta2.adapters.clearml.bundle import ClearMLStore, S3Roots
from cveta2.adapters.files.bundle import LocalBundleFiles
from cveta2.adapters.files.bundle_paths import LocalRoots
from cveta2.adapters.files.media import LocalMediaInspector
from cveta2.application.ports.dataset_bundle import BundleServices
from cveta2.application.use_cases.dataset_bundle import (
    prepare_dataset as prepare,
)
from cveta2.application.use_cases.dataset_bundle import (
    upload_dataset as publish,
)
from cveta2.domain.bundle.models import Publication
from cveta2.domain.bundle.preparation import PreparedDataset, PrepareOptions


def bundle_services() -> BundleServices:
    """Construct services without opening files or initializing the SDK."""
    return BundleServices(
        HttpClassApi(),
        ClearMLStore(),
        S3Roots(),
        LocalRoots(),
        LocalBundleFiles(),
        LocalMediaInspector(),
    )


def prepare_dataset(
    source: Path, directory: Path, options: PrepareOptions
) -> PreparedDataset:
    """Prepare local review evidence using runtime configuration."""
    return prepare(source, directory, options, bundle_services())


def upload_dataset(directory: Path) -> Publication:
    """Revalidate reviewed evidence and finalize an explicit ClearML child."""
    return publish(directory, bundle_services())

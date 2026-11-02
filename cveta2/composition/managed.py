"""Construct effects for managed datasets without discovering policy inward."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from cveta2.adapters.class_api.http import HttpClassApi
from cveta2.adapters.clearml.bundle import ClearMLStore, S3Roots
from cveta2.adapters.clearml.managed_sources import ClearMLSources
from cveta2.adapters.config.project import load_project_config
from cveta2.adapters.config.settings import (
    CacheConfig,
    CvatConfig,
    ImageCacheConfig,
    NetworkConfig,
    get_config_path,
)
from cveta2.adapters.cvat.managed_feedback import CvatFeedback
from cveta2.adapters.cvat.managed_sources import CvatSources
from cveta2.adapters.files.bundle import LocalBundleFiles
from cveta2.adapters.files.bundle_paths import LocalRoots
from cveta2.adapters.files.managed_feedback import LocalFeedbackLedger
from cveta2.adapters.files.managed_preparation import LocalManagedPreparationFiles
from cveta2.adapters.files.managed_sources import LocalSourceFiles
from cveta2.adapters.files.media import LocalMediaInspector
from cveta2.adapters.files.verification import read_csv, read_csv_bytes
from cveta2.adapters.s3.managed_sources import S3CsvSources
from cveta2.application.client.assembly import task_to_records
from cveta2.application.use_cases.managed_preparation import prepare_managed
from cveta2.application.use_cases.managed_publication import (
    ManagedPublicationServices,
    publish_prepared,
    report_prepared,
)
from cveta2.application.use_cases.managed_sources import fetch_sources
from cveta2.composition.client import CvatClient
from cveta2.composition.runtime import configure_data_timeout, configure_network
from cveta2.domain.bundle.classes import reconcile_classes
from cveta2.domain.bundle.models import (
    ApiClass,
    DatasetMetadata,
    DatasetParent,
    ImageRoots,
    Publication,
)
from cveta2.domain.managed.models import DatasetDefinition, ManagedError, ProjectConfig
from cveta2.domain.managed.policies import compare_frames
from cveta2.domain.managed.preparation import FeedbackOutcome, PreparationSummary


def _selection(
    config_path: Path | None, project_config: Path | None
) -> tuple[Path, ProjectConfig]:
    path = get_config_path(config_path)
    return path, load_project_config(path, project_config)


def _definition(config: ProjectConfig, name: str) -> DatasetDefinition:
    try:
        return config.datasets[name]
    except KeyError as error:
        raise ManagedError(f"Unknown managed dataset: {name}") from error


def _registry_hash(records: list[ApiClass]) -> str:
    content = [
        r.model_dump(mode="json") for r in sorted(records, key=lambda r: r.number)
    ]
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _parent(
    definition: DatasetDefinition,
) -> tuple[DatasetParent | None, DatasetMetadata | None]:
    parent = ClearMLStore().latest(
        definition.clearml.project, definition.clearml.dataset
    )
    metadata = (
        LocalBundleFiles().read_metadata(parent.metadata_path)
        if parent and parent.metadata_path
        else None
    )
    return parent, metadata


def _metadata(  # noqa: PLR0913, PLR0917 - resolved policy and selected storage.
    path: Path,
    config: ProjectConfig,
    definition: DatasetDefinition,
    records: list[ApiClass],
    previous: DatasetMetadata | None,
    project_config: Path | None = None,
) -> DatasetMetadata:
    update = reconcile_classes(previous.classes if previous else {}, records)
    known = {info.prod_id for info in update.classes.values()}
    if set(definition.empty_classes) - known:
        raise ManagedError("Shared exclusion policy contains unknown class identities")
    classes = {
        name: info.model_copy(
            update={"empty": info.prod_id in definition.empty_classes}
        )
        for name, info in update.classes.items()
    }
    return DatasetMetadata(
        api_url=definition.api_url,
        classes=classes,
        images=_image_roots(path, config, definition, project_config),
    )


def _image_roots(
    path: Path,
    config: ProjectConfig,
    definition: DatasetDefinition,
    project_config: Path | None = None,
) -> ImageRoots:
    roots = []
    images = ImageCacheConfig.load(path, project_path=project_config)
    cache = CacheConfig.load(path, project_path=project_config)
    if cache.images_root:
        roots.append(str(cache.images_root))
    for source in definition.sources:
        if source.project is not None:
            project = config.projects[source.project]
            for key in dict.fromkeys((source.project, project.name)):
                if local := images.get_cache_dir(key):
                    roots.append(str(local))
                if local := cache.for_project(key).images_root:
                    roots.append(str(local))
    return ImageRoots(
        local_root=list(dict.fromkeys(roots)), s3_root=definition.s3_roots
    )


@contextmanager
def _client(path: Path, project_config: Path | None) -> Iterator[CvatClient]:
    cfg = CvatConfig.load(path, project_path=project_config)
    configure_data_timeout(cfg.request_timeout)
    configure_network(NetworkConfig.resolve(path, project_path=project_config))
    with CvatClient(cfg) as client:
        yield client


def list_datasets(
    *, config_path: Path | None = None, project_config: Path | None = None
) -> list[dict[str, Any]]:
    """Inspect local definitions with no SDK initialization."""
    _, config = _selection(config_path, project_config)
    return [
        {"name": name, **definition.model_dump(mode="json")}
        for name, definition in sorted(config.datasets.items())
    ]


def show_dataset(
    name: str, *, config_path: Path | None = None, project_config: Path | None = None
) -> dict[str, Any]:
    """Show exact configured mapping and finalized parent."""
    _, config = _selection(config_path, project_config)
    definition = _definition(config, name)
    parent, _ = _parent(definition)
    return {
        "name": name,
        "definition": definition.model_dump(mode="json"),
        "parent_id": parent.dataset_id if parent else None,
        "parent_version": parent.version if parent else None,
    }


def dataset_versions(
    name: str, *, config_path: Path | None = None, project_config: Path | None = None
) -> list[dict[str, str | None]]:
    """List finalized exact-destination versions."""
    _, config = _selection(config_path, project_config)
    definition = _definition(config, name)
    return ClearMLStore().versions(
        definition.clearml.project, definition.clearml.dataset
    )


def fetch_dataset(
    name: str,
    *,
    output_dir: Path,
    refresh: bool = False,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> dict[str, Any]:
    """Capture every source and preserve independent original evidence."""
    path, config = _selection(config_path, project_config)
    definition = _definition(config, name)
    records = HttpClassApi().fetch(definition.api_url)
    parent, _ = _parent(definition)
    previous = ClearMLSources().read_snapshot(parent.dataset_id) if parent else None
    files = LocalSourceFiles()
    with _client(path, project_config) as client:
        snapshot, frame = fetch_sources(
            config,
            definition,
            registry_hash=_registry_hash(records),
            cvat=CvatSources(client.api, task_to_records),
            s3=S3CsvSources(),
            files=files,
            previous=previous,
            parent_id=parent.dataset_id if parent else None,
            refresh=refresh,
        )
    files.export(output_dir, snapshot, frame)
    return {
        "directory": str(output_dir),
        "rows": len(frame),
        "parent_id": snapshot.parent_id,
        "sources": [
            {
                "name": source.name,
                "fetched": source.fetched,
                "reused": source.reused,
                "content_hash": source.content_hash,
            }
            for source in snapshot.sources
        ],
    }


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
    """Prepare transformed input using supplied policy and constructed effects."""
    path, config = _selection(config_path, project_config)
    definition = _definition(config, name)
    records = HttpClassApi().fetch(definition.api_url)
    parent, previous = _parent(definition)
    if (
        previous
        and previous.managed
        and previous.managed.definition.splits != definition.splits
    ):
        raise ManagedError("Split policy changed; select a new dataset lineage")
    return prepare_managed(
        config,
        name,
        csv,
        source,
        output_dir,
        _metadata(path, config, definition, records, previous, project_config),
        registry_hash=_registry_hash(records),
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        parent_id=parent.dataset_id if parent else None,
        parent_version=parent.version if parent else None,
        parent_metadata=previous,
        clean=clean,
    )


def _comparison_frame(reference: str) -> pd.DataFrame:
    path = Path(reference)
    if path.is_dir():
        path = path / "dataset.csv"
    if path.is_file():
        return read_csv(path)
    return read_csv_bytes(
        ClearMLSources().read_files(reference, ("dataset.csv",))["dataset.csv"],
        source=reference,
    )


def compare_datasets(
    old: str,
    new: str,
    *,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> dict[str, Any]:
    """Compare local or immutable remote datasets without altering them."""
    _selection(config_path, project_config)
    return dict(compare_frames(_comparison_frame(old), _comparison_frame(new)))


def report_dataset_errors(
    prepared: Path,
    *,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> FeedbackOutcome:
    """Resume feedback delivery through the composed managed workflow."""
    with _prepared_effects(prepared, config_path, project_config) as (config, services):
        return report_prepared(config, prepared, services=services)


def publish_dataset(
    prepared: Path,
    *,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> Publication:
    """Publish reviewed stable payload only after prerequisite checks."""
    with _prepared_effects(prepared, config_path, project_config) as (config, services):
        return publish_prepared(config, prepared, services=services)


@contextmanager
def _prepared_effects(
    prepared: Path,
    config_path: Path | None,
    project_config: Path | None,
) -> Iterator[tuple[ProjectConfig, ManagedPublicationServices]]:

    path, config = _selection(config_path, project_config)
    files = LocalManagedPreparationFiles()
    loaded = files.load_prepared(prepared)
    definition = _definition(config, loaded.record.name)
    local_roots = _image_roots(path, config, definition, project_config).local_root
    with _client(path, project_config) as client:
        yield (
            config,
            ManagedPublicationServices(
                files=files,
                media=LocalMediaInspector(),
                remote=ClearMLStore(),
                registry=HttpClassApi(),
                cvat=CvatSources(client.api, task_to_records),
                s3=S3CsvSources(),
                roots=LocalRoots(),
                s3_roots=S3Roots(),
                feedback=CvatFeedback(client.api),
                ledger=LocalFeedbackLedger(prepared),
                local_roots=local_roots,
            ),
        )

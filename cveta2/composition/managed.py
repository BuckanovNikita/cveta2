"""Construct effects for managed datasets without discovering policy inward."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

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
from cveta2.adapters.files.managed_feedback import LocalFeedbackLedger, shared_ledger_path
from cveta2.adapters.files.managed_preparation import LocalManagedPreparationFiles
from cveta2.adapters.files.managed_sources import LocalSourceFiles
from cveta2.adapters.files.media import LocalMediaInspector
from cveta2.adapters.files.verification import read_csv, read_csv_bytes
from cveta2.adapters.s3.managed_sources import S3CsvSources
from cveta2.application.client.assembly import task_to_records
from cveta2.application.use_cases.managed_preparation import check_parent, prepare_managed
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
    ClassInfo,
    DatasetMetadata,
    DatasetParent,
    ImageRoots,
    Publication,
    UploadError,
)
from cveta2.domain.bundle.validation import excluded_class_rows, missing_active_classes
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.managed.models import DatasetDefinition, ManagedError, ProjectConfig, dataset_definition
from cveta2.domain.managed.policies import compare_frames
from cveta2.domain.managed.preparation import FeedbackOutcome, PreparationSummary


def _selection(config_path: Path | None, project_config: Path | None) -> tuple[Path, ProjectConfig]:
    path = get_config_path(config_path)
    return path, load_project_config(path, project_config)


def _parent(
    definition: DatasetDefinition,
) -> tuple[DatasetParent | None, DatasetMetadata | None]:
    """Return the latest version and its metadata; an unreadable ``dataset.yaml`` raises."""
    parent = ClearMLStore().latest(definition.clearml.project, definition.clearml.dataset)
    metadata = LocalBundleFiles().read_metadata(parent.metadata_path) if parent and parent.metadata_path else None
    return parent, metadata


def _first_parent(
    definition: DatasetDefinition,
) -> tuple[DatasetParent | None, DatasetMetadata | None]:
    """Return the latest version for ``--first``, which only needs to know whether it is managed.

    A missing, unreadable or invalid ``dataset.yaml`` makes the version count as not
    managed, with one warning; only metadata that parses and carries ``managed`` is managed.
    """
    parent = ClearMLStore().latest(definition.clearml.project, definition.clearml.dataset)
    if parent is None:
        return None, None
    if parent.metadata_path is None:
        reason = "нет dataset.yaml"
    else:
        try:
            return parent, LocalBundleFiles().read_metadata(parent.metadata_path)
        except UploadError as error:
            reason = f"dataset.yaml не читается: {error}"
    logger.warning(f"dataset prepare --first: последняя версия {parent.dataset_id} считается неуправляемой ({reason})")
    return parent, None


def _classes(
    definition: DatasetDefinition,
    records: list[ApiClass],
    previous: DatasetMetadata | None,
) -> dict[str, ClassInfo]:
    """Reconcile the class registry with the parent's and apply the shared exclusion policy."""
    update = reconcile_classes(previous.classes if previous else {}, records)
    known = {info.prod_id for info in update.classes.values()}
    if set(definition.empty_classes) - known:
        raise ManagedError("Shared exclusion policy contains unknown class identities")
    return {
        name: info.model_copy(update={"empty": info.prod_id in definition.empty_classes})
        for name, info in update.classes.items()
    }


def _metadata(  # noqa: PLR0913, PLR0917 - resolved policy and selected storage.
    path: Path,
    config: ProjectConfig,
    definition: DatasetDefinition,
    records: list[ApiClass],
    previous: DatasetMetadata | None,
    project_config: Path | None = None,
) -> DatasetMetadata:
    return DatasetMetadata(
        api_url=definition.api_url,
        classes=_classes(definition, records, previous),
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
    # Earlier personal files keyed local paths by the CVAT display name.
    # Only that layout needs a live lookup. Ordinary key-based preparation stays offline.
    local_names = (
        images.projects.keys() | {key for key, value in cache.projects.items() if value.images_root}
    ) - config.projects.keys()
    sources = [source.project for source in definition.sources if source.project is not None]
    names: dict[int, str] = {}
    if sources and local_names:
        with _client(path, project_config) as client:
            names = {project.id: project.name for project in client.list_projects() if project.name in local_names}
    for key in sources:
        project_id = config.projects[key].id
        name = names.get(project_id, key)
        if local := images.get_cache_dir(name, project_id):
            roots.append(str(local))
        if local := cache.for_project(name, project_id).images_root:
            roots.append(str(local))
    return ImageRoots(local_root=list(dict.fromkeys(roots)), s3_root=definition.s3_roots)


@contextmanager
def _client(path: Path, project_config: Path | None) -> Iterator[CvatClient]:
    cfg = CvatConfig.load(path, project_path=project_config)
    configure_data_timeout(cfg.request_timeout)
    configure_network(NetworkConfig.resolve(path, project_path=project_config))
    with CvatClient(cfg) as client:
        yield client


def list_datasets(*, config_path: Path | None = None, project_config: Path | None = None) -> list[dict[str, Any]]:
    """Inspect local definitions with no SDK initialization."""
    _, config = _selection(config_path, project_config)
    return [
        {"name": name, **definition.model_dump(mode="json")} for name, definition in sorted(config.datasets.items())
    ]


def show_dataset(name: str, *, config_path: Path | None = None, project_config: Path | None = None) -> dict[str, Any]:
    """Show exact configured mapping and finalized parent."""
    _, config = _selection(config_path, project_config)
    definition = dataset_definition(config, name)
    parent = ClearMLStore().latest(definition.clearml.project, definition.clearml.dataset)
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
    definition = dataset_definition(config, name)
    return ClearMLStore().versions(definition.clearml.project, definition.clearml.dataset)


def _warn_coverage(
    definition: DatasetDefinition,
    records: list[ApiClass],
    previous: DatasetMetadata | None,
    frame: pd.DataFrame,
) -> tuple[int | None, list[str] | None]:
    """Warn about class coverage of the fetched rows; fetch never fails because of it.

    Returns ``(None, None)`` when the classes cannot be built.
    """
    try:
        metadata = DatasetMetadata(api_url=definition.api_url, classes=_classes(definition, records, previous))
        excluded = excluded_class_rows(frame, metadata)
        missing = list(missing_active_classes(frame, metadata))
    except Cveta2Error as error:
        logger.warning(f"Не удалось проверить классы: {error}")
        return None, None
    if excluded:
        logger.warning(f"Строк с исключёнными классами: {excluded}. dataset prepare отклонит их.")
    if missing:
        logger.warning(
            f"Нет ни одного bbox у классов: {', '.join(missing)}. "
            "Добавьте данные с ними или исключите класс через empty_classes."
        )
    return excluded, missing


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
    definition = dataset_definition(config, name)
    records = HttpClassApi().fetch(definition.api_url)
    parent = ClearMLStore().latest(definition.clearml.project, definition.clearml.dataset)
    previous = None
    previous_cvat = None
    metadata = None
    if parent is not None and parent.metadata_path is not None:
        try:
            metadata = LocalBundleFiles().read_metadata(parent.metadata_path)
        except UploadError as error:
            logger.warning(
                f"dataset.yaml последней версии {parent.dataset_id} не читается, источники выгружаются заново: {error}"
            )
    # Only a managed version is a lineage to continue: nothing else of it, tasks.yaml included, is read or reused.
    if parent is not None and metadata is not None and metadata.managed is not None:
        previous = ClearMLSources().read_snapshot(parent.dataset_id)
        previous_cvat = metadata.managed.cvat
    files = LocalSourceFiles()
    with _client(path, project_config) as client:
        snapshot, frame = fetch_sources(
            config,
            definition,
            registry=records,
            cvat=CvatSources(client.api, task_to_records),
            s3=S3CsvSources(),
            files=files,
            previous=previous,
            previous_cvat=previous_cvat,
            parent_id=parent.dataset_id if parent else None,
            refresh=refresh,
        )
    files.export(output_dir, snapshot, frame)
    # Only a managed latest version is read for classes, like for the lineage above.
    managed_metadata = metadata if metadata is not None and metadata.managed is not None else None
    excluded, missing = _warn_coverage(definition, records, managed_metadata, frame)
    return {
        "directory": str(output_dir),
        "rows": len(frame),
        "parent_id": snapshot.parent_id,
        "excluded_class_rows": excluded,
        "missing_classes": missing,
        "sources": [
            {
                "name": source.name,
                "fetched": source.fetched,
                "reused": source.reused,
                "skipped": source.skipped,
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
    clean: bool = True,
    first: bool = False,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> PreparationSummary:
    """Prepare transformed input using supplied policy and constructed effects.

    With *first* the latest version is only checked to be non-managed; its classes,
    splits and rows are not used.
    """
    path, config = _selection(config_path, project_config)
    definition = dataset_definition(config, name)
    records = HttpClassApi().fetch(definition.api_url)
    parent, previous = _first_parent(definition) if first else _parent(definition)
    # Refuse the wrong mode before reconciling classes against a parent that will not be used.
    check_parent(parent.dataset_id if parent else None, previous, first=first)
    return prepare_managed(
        config,
        name,
        csv,
        source,
        output_dir,
        _metadata(path, config, definition, records, None if first else previous, project_config),
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        s3_roots=S3Roots(),
        parent_id=parent.dataset_id if parent else None,
        parent_version=parent.version if parent else None,
        parent_metadata=previous,
        clean=clean,
        first=first,
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
    force_resplit: bool = False,
    config_path: Path | None = None,
    project_config: Path | None = None,
) -> Publication:
    """Publish the preparation's current files once they pass every check."""
    with _prepared_effects(prepared, config_path, project_config) as (config, services):
        return publish_prepared(config, prepared, services=services, force_resplit=force_resplit)


@contextmanager
def _prepared_effects(
    prepared: Path,
    config_path: Path | None,
    project_config: Path | None,
) -> Iterator[tuple[ProjectConfig, ManagedPublicationServices]]:

    path, config = _selection(config_path, project_config)
    files = LocalManagedPreparationFiles()
    loaded = files.load_prepared(prepared)
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
                ledger=LocalFeedbackLedger(
                    prepared,
                    shared_ledger_path(path.parent / "managed-feedback", loaded.ledger_key),
                ),
            ),
        )

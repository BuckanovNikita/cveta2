"""Prepare explicit review evidence, then revalidate before publication."""

from dataclasses import replace
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from cveta2.application.ports.dataset_bundle import BundleServices
from cveta2.domain.bundle.classes import reconcile_classes
from cveta2.domain.bundle.models import (
    BundleValidation,
    ClassUpdate,
    DatasetMetadata,
    DatasetParent,
    ImageRoots,
    Publication,
    TaskManifest,
    UploadError,
)
from cveta2.domain.bundle.preparation import (
    BundleDraft,
    Decision,
    MissingDecisions,
    PreparedDataset,
    PrepareOptions,
    StoredBundle,
)
from cveta2.domain.bundle.tasks import derive_tasks
from cveta2.domain.bundle.validation import validate_bundle
from cveta2.domain.verification.models import ValidationOptions


def _classes(
    previous: DatasetMetadata | None,
    api_url: str,
    options: PrepareOptions,
    services: BundleServices,
) -> ClassUpdate:
    update = reconcile_classes(
        previous.classes if previous else {}, services.api.fetch(api_url)
    )
    decisions = []
    if previous and update.changes and not options.accept_class_changes:
        decisions.append(
            Decision(
                "class_changes",
                "Подтвердите изменения классов: "
                + ", ".join(
                    f"{c.kind}: {c.name} ({c.prod_id})" for c in update.changes
                ),
            )
        )
    classes = dict(update.classes)
    added = {change.prod_id for change in update.changes if change.kind == "added"}
    identities = {info.prod_id for info in classes.values()}
    if unknown := options.class_empty.keys() - identities:
        raise UploadError(f"Неизвестные номера классов в настройках: {sorted(unknown)}")
    for name, info in classes.items():
        if info.prod_id in options.class_empty:
            classes[name] = info.model_copy(
                update={"empty": options.class_empty[info.prod_id]}
            )
        elif info.prod_id in added and not options.accept_default_classes:
            decisions.append(
                Decision(
                    "class_empty",
                    f"Исключать класс {name!r} ({info.prod_id})?",
                    ("false", "true"),
                    info.prod_id,
                )
            )
    if decisions:
        raise MissingDecisions(tuple(decisions))
    return ClassUpdate(classes, update.changes)


def _roots(
    frame: pd.DataFrame, roots: ImageRoots, services: BundleServices
) -> ImageRoots:
    canonical = ImageRoots(
        local_root=list(
            dict.fromkeys(
                services.roots.check_local_root(root) for root in roots.local_root
            )
        ),
        s3_root=list(dict.fromkeys(roots.s3_root)),
    )
    if uncovered := services.roots.uncovered_paths(frame, canonical):
        raise MissingDecisions(
            (
                Decision(
                    "local_roots",
                    "Укажите разрешённые каталоги изображений:\n"
                    + "\n".join(uncovered),
                    tuple(uncovered),
                ),
            )
        )
    services.roots.check_s3_paths(frame, canonical)
    for root in canonical.s3_root:
        services.s3.check_root(root)
    return canonical


def _validate(
    frame: pd.DataFrame, metadata: DatasetMetadata, services: BundleServices
) -> BundleValidation:
    inspection = services.media.inspect(
        frame,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
    )
    return validate_bundle(frame, metadata, inspection=inspection)


def _parent_metadata(
    parent: DatasetParent | None, services: BundleServices
) -> DatasetMetadata | None:
    if parent is None:
        return None
    if parent.metadata_path is None:
        raise UploadError(
            f"Родитель {parent.dataset_id} не содержит dataset.yaml. "
            "Выберите новое имя датасета."
        )
    return services.files.read_metadata(parent.metadata_path)


def prepare_dataset(
    source: Path, directory: Path, options: PrepareOptions, services: BundleServices
) -> PreparedDataset:
    """Write reviewable local evidence without creating a remote dataset."""
    try:
        options = PrepareOptions.model_validate(options.model_dump())
    except ValidationError as error:
        raise UploadError(f"Invalid preparation options: {error}") from error
    if not options.project.strip():
        raise UploadError("Укажите непустой проект ClearML.")
    if not options.dataset_name or not options.dataset_name.strip():
        raise MissingDecisions(
            (Decision("dataset_name", "Укажите имя датасета ClearML."),)
        )
    snapshot = services.files.read_source(source)
    parent = services.datasets.latest(options.project, options.dataset_name)
    previous = _parent_metadata(parent, services)
    api_url = options.api_url or (previous.api_url if previous else None)
    if not api_url:
        raise MissingDecisions((Decision("api_url", "Укажите URL API классов."),))
    try:
        DatasetMetadata(api_url=api_url, classes={})
    except ValidationError as error:
        raise UploadError(
            f"Invalid preparation options or API metadata: {error}"
        ) from error
    update = _classes(previous, api_url, options, services)
    old_roots = previous.images if previous else ImageRoots()
    roots = _roots(
        snapshot.tables.dataset,
        ImageRoots(
            local_root=[*old_roots.local_root, *options.local_roots],
            s3_root=[*old_roots.s3_root, *options.s3_roots],
        ),
        services,
    )
    metadata = DatasetMetadata(api_url=api_url, classes=update.classes, images=roots)
    validation = _validate(snapshot.tables.dataset, metadata, services)
    try:
        tasks = derive_tasks(snapshot.tables, validation.result.clean)
    except UploadError as error:
        tasks = TaskManifest(included=[], obsolete=[])
        validation = replace(validation, blockers=(*validation.blockers, str(error)))
    ready = (
        not validation.blockers
        and not validation.result.structural_errors
        and (options.clean or not validation.result.requires_cleanup)
    )
    return services.files.save_preparation(
        directory,
        BundleDraft(
            source=snapshot,
            metadata=metadata,
            tasks=tasks,
            validation=validation,
            options=options,
            parent=parent,
            changes=update.changes,
            ready=ready,
        ),
    )


def _check_parent(bundle: StoredBundle, services: BundleServices) -> None:
    options = bundle.record.options
    parent = services.datasets.latest(options.project, options.dataset_name or "")
    current = (parent.dataset_id, parent.version) if parent else (None, None)
    if current != (bundle.record.parent_id, bundle.record.parent_version):
        raise UploadError("Latest parent changed; подготовьте датасет заново.")


def _check_bundle(bundle: StoredBundle, services: BundleServices) -> None:
    _check_parent(bundle, services)
    metadata = bundle.metadata
    update = reconcile_classes(metadata.classes, services.api.fetch(metadata.api_url))
    if update.changes or update.classes != metadata.classes:
        raise UploadError("Class identities changed; подготовьте датасет заново.")
    roots = _roots(bundle.source.tables.dataset, metadata.images, services)
    if roots != metadata.images:
        raise UploadError("Корни изображений изменились; подготовьте датасет заново.")
    retained = _validate(bundle.dataset, metadata, services)
    if (
        retained.blockers
        or retained.result.structural_errors
        or retained.result.requires_cleanup
    ):
        raise UploadError(
            "Подготовленные данные больше не проходят проверку: "
            + "; ".join(
                (*retained.blockers, *(i.message for i in retained.result.issues))
            )
        )
    original = _validate(bundle.source.tables.dataset, metadata, services)
    if original.blockers or original.result.structural_errors:
        raise UploadError(
            "Исходные данные больше не проходят проверку; подготовьте датасет заново."
        )
    if original.result.requires_cleanup and not bundle.record.options.clean:
        raise UploadError("Очистка исходных данных не была разрешена.")
    tasks = derive_tasks(bundle.source.tables, original.result.clean)
    if tasks != bundle.tasks or not services.files.payload_matches(
        bundle, original.result.clean, tasks
    ):
        raise UploadError(
            "Результат повторной проверки изменился; подготовьте датасет заново."
        )


def upload_dataset(directory: Path, services: BundleServices) -> Publication:
    """Publish only unchanged, fully revalidated bytes from a reviewed bundle."""
    with services.files.stage_prepared(directory) as bundle:
        _check_bundle(bundle, services)
        # Remote stores provide no compare-and-swap; narrow the parent race by
        # checking again after all potentially slow filesystem/media/network reads.
        _check_parent(bundle, services)
        options = bundle.record.options
        return services.datasets.publish(
            options.project,
            options.dataset_name or "",
            bundle.record.parent_id,
            bundle.directory,
        )

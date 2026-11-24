"""Prepare a bundle from fetch output, then publish whatever the bundle's current files make valid."""

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
from loguru import logger
from pydantic import ValidationError

from cveta2.application.ports.dataset_bundle import BundleServices
from cveta2.domain.bundle.classes import reconcile_classes
from cveta2.domain.bundle.models import (
    BundleValidation,
    ClassInfo,
    ClassUpdate,
    DatasetMetadata,
    DatasetParent,
    ImageRoots,
    Publication,
    TaskManifest,
    UploadError,
)
from cveta2.domain.bundle.preparation import (
    PUBLISHED_NAMES,
    SOURCES_ARCHIVE,
    BundleProposal,
    CurrentBundle,
    Decision,
    MissingDecisions,
    PreparedDataset,
    PrepareOptions,
)
from cveta2.domain.bundle.splits import changed_splits, published_splits
from cveta2.domain.bundle.tasks import derive_tasks, trace_tasks
from cveta2.domain.bundle.validation import missing_active_classes, validate_bundle
from cveta2.domain.managed.models import ClearMLDestination
from cveta2.domain.verification.models import ValidationOptions

# How many paths, rows or images one refusal lists before it only counts the rest.
_LISTED = 20


def _classes(
    previous: DatasetMetadata | None,
    api_url: str,
    options: PrepareOptions,
    services: BundleServices,
) -> ClassUpdate:
    update = reconcile_classes(previous.classes if previous else {}, services.api.fetch(api_url))
    decisions = []
    if previous and update.changes and not options.accept_class_changes:
        decisions.append(
            Decision(
                "class_changes",
                "Подтвердите изменения классов: "
                + ", ".join(f"{c.kind}: {c.name} ({c.prod_id})" for c in update.changes),
            )
        )
    classes = dict(update.classes)
    added = {change.prod_id for change in update.changes if change.kind == "added"}
    identities = {info.prod_id for info in classes.values()}
    if unknown := options.class_empty.keys() - identities:
        raise UploadError(f"Неизвестные номера классов в настройках: {sorted(unknown)}")
    for name, info in classes.items():
        if info.prod_id in options.class_empty:
            classes[name] = info.model_copy(update={"empty": options.class_empty[info.prod_id]})
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


def _roots(frame: pd.DataFrame, roots: ImageRoots, services: BundleServices) -> ImageRoots:
    canonical = ImageRoots(
        local_root=list(dict.fromkeys(services.roots.check_local_root(root) for root in roots.local_root)),
        s3_root=list(dict.fromkeys(roots.s3_root)),
    )
    if uncovered := services.roots.uncovered_paths(frame, canonical):
        raise MissingDecisions(
            (
                Decision(
                    "local_roots",
                    "Укажите разрешённые каталоги изображений:\n" + "\n".join(uncovered),
                    tuple(uncovered),
                ),
            )
        )
    services.roots.check_s3_paths(frame, canonical)
    for root in canonical.s3_root:
        services.s3.check_root(root)
    return canonical


def _validate(frame: pd.DataFrame, metadata: DatasetMetadata, services: BundleServices) -> BundleValidation:
    inspection = services.media.inspect(
        frame,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
    )
    return validate_bundle(frame, metadata, inspection=inspection)


def _parent_metadata(parent: DatasetParent | None, services: BundleServices) -> DatasetMetadata | None:
    if parent is None:
        return None
    if parent.metadata_path is None:
        raise UploadError(f"Родитель {parent.dataset_id} не содержит dataset.yaml. Выберите новое имя датасета.")
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
        raise MissingDecisions((Decision("dataset_name", "Укажите имя датасета ClearML."),))
    try:
        destination = ClearMLDestination(
            project=options.project, dataset=options.dataset_name, output_uri=options.output_uri
        )
    except ValidationError as error:
        raise UploadError(f"Invalid preparation options: {error}") from error
    snapshot = services.files.read_source(source)
    parent = services.datasets.latest(options.project, options.dataset_name)
    previous = _parent_metadata(parent, services)
    api_url = options.api_url or (previous.api_url if previous else None)
    if not api_url:
        raise MissingDecisions((Decision("api_url", "Укажите URL API классов."),))
    try:
        DatasetMetadata(api_url=api_url, classes={})
    except ValidationError as error:
        raise UploadError(f"Invalid preparation options or API metadata: {error}") from error
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
    metadata = DatasetMetadata(clearml=destination, api_url=api_url, classes=update.classes, images=roots)
    validation = _validate(snapshot.tables.dataset, metadata, services)
    blockers = list(validation.blockers)
    try:
        tasks = derive_tasks(snapshot.tables, validation.result.clean)
    except UploadError as error:
        tasks = TaskManifest(included=[], obsolete=[])
        blockers.append(str(error))
    if validation.result.requires_cleanup and not options.clean:
        blockers.append(
            f"Нужна очистка: отклонено {len(validation.result.broken)} строк; "
            "запустите verify без --no-clean или исправьте исходные данные."
        )
    return services.files.save_preparation(
        directory,
        BundleProposal(
            source=snapshot,
            metadata=metadata,
            tasks=tasks,
            validation=validation,
            destination=destination,
            parent=parent,
            changes=update.changes,
            blockers=tuple(blockers),
        ),
    )


def _listing(items: Sequence[str]) -> str:
    """One item per line, at most ``_LISTED`` of them, then the count of the rest."""
    lines = [f"  {item}" for item in items[:_LISTED]]
    if len(items) > _LISTED:
        lines.append(f"  … и ещё {len(items) - _LISTED}")
    return "\n".join(lines)


def _identity(parent: DatasetParent | None) -> tuple[str | None, str | None]:
    return (parent.dataset_id, parent.version) if parent else (None, None)


def _version(parent_id: str | None, version: str | None) -> str:
    if parent_id is None:
        return "нет версии"
    return f"{parent_id} (версия {version or 'не указана'})"


def _destination(bundle: CurrentBundle) -> ClearMLDestination:
    """Check 1: ``dataset.yaml`` names where to publish."""
    if bundle.metadata.clearml is None:
        raise UploadError(
            "В dataset.yaml нет назначения публикации: добавьте блок clearml с ключами "
            "clearml.project и clearml.dataset."
        )
    return bundle.metadata.clearml


def _check_recorded_parent(
    bundle: CurrentBundle, destination: ClearMLDestination, parent: DatasetParent | None
) -> None:
    """Check 2: for the destination ``verify`` saw, the latest version must be the one it recorded."""
    recorded = bundle.recorded
    if recorded is None:
        logger.warning(
            "В report.json нет записи verify о назначении и родителе: "
            "нельзя проверить, что после verify не появилась новая версия."
        )
        return
    if (recorded.project, recorded.dataset) != (destination.project, destination.dataset):
        logger.warning(
            f"Назначение в dataset.yaml ({destination.project}/{destination.dataset}) отличается от "
            f"записанного verify ({recorded.project}/{recorded.dataset}): родитель не сверяется с записью verify."
        )
        return
    current, seen = _identity(parent), (recorded.parent_id, recorded.parent_version)
    if current != seen:
        raise UploadError(
            f"После verify появилась новая версия {destination.project}/{destination.dataset}: "
            f"сейчас последняя {_version(*current)}, verify видел {_version(*seen)}. Запустите cveta2 verify заново."
        )


def _refuse_managed(parent: DatasetParent | None, previous: DatasetMetadata | None) -> None:
    if parent is not None and previous is not None and previous.managed is not None:
        raise UploadError(
            f"Родитель {parent.dataset_id} — управляемый датасет (в его dataset.yaml есть блок managed); "
            "его версии публикует cveta2 dataset publish. Выберите другое clearml.dataset в dataset.yaml."
        )


def _warn_previous_publication(bundle: CurrentBundle) -> None:
    previous = bundle.previous_publication
    if previous is None:
        return
    dataset_id = previous.get("dataset_id")
    if isinstance(dataset_id, str):
        version = previous.get("version")
        logger.warning(
            f"Каталог уже опубликован (publication.json): датасет {dataset_id}"
            + (f", версия {version}" if isinstance(version, str) else "")
            + ". Публикуется ещё одна версия."
        )
    else:
        logger.warning("В каталоге есть publication.json, но его нельзя прочитать: каталог мог быть уже опубликован.")


def _identities(classes: dict[str, ClassInfo]) -> dict[str, tuple[int, tuple[str, ...]]]:
    return {name: (info.prod_id, tuple(sorted(info.alt_names))) for name, info in classes.items()}


def _check_classes(metadata: DatasetMetadata, previous: DatasetMetadata | None, services: BundleServices) -> None:
    """Check 3: names, numbers and aliases are the registry's; ``empty`` flags are the user's."""
    update = reconcile_classes(previous.classes if previous else {}, services.api.fetch(metadata.api_url))
    expected, actual = _identities(update.classes), _identities(metadata.classes)
    if differing := sorted(name for name in expected.keys() | actual.keys() if expected.get(name) != actual.get(name)):
        raise UploadError(
            f"Классы dataset.yaml не совпадают с реестром {metadata.api_url}: {', '.join(differing)}. "
            "Имена, prod_id и alt_names задаёт реестр (empty — ваш выбор): "
            "верните их или запустите cveta2 verify заново."
        )


def _check_roots(bundle: CurrentBundle, destination: ClearMLDestination, services: BundleServices) -> None:
    """Check 4: every image file exists inside a local root; S3 roots and the output bucket can be listed."""
    roots, frame = bundle.metadata.images, bundle.dataset
    for root in roots.local_root:
        services.roots.check_local_root(root)
    if missing := services.roots.missing_files(frame):
        raise UploadError(
            f"Нет файлов изображений из image_path ({len(missing)}):\n{_listing(missing)}\n"
            "Верните файлы или удалите их строки из dataset.csv."
        )
    if uncovered := services.roots.uncovered_paths(frame, roots):
        raise UploadError(
            f"image_path вне локальных корней images.local_root ({len(uncovered)}):\n{_listing(uncovered)}\n"
            "Добавьте их каталог в images.local_root в dataset.yaml."
        )
    services.roots.check_s3_paths(frame, roots)
    for root in roots.s3_root:
        services.s3.check_root(root)
    if destination.output_uri is not None and destination.output_uri.startswith("s3://"):
        bucket = destination.output_uri.removeprefix("s3://").split("/", 1)[0]
        services.s3.check_root(f"s3://{bucket}")


def _check_rows(
    bundle: CurrentBundle, parent: DatasetParent | None, services: BundleServices, *, force_resplit: bool
) -> None:
    """Check 5: the rows pass validation untouched, cover every active class and keep published splits."""
    metadata = bundle.metadata
    validation = _validate(bundle.dataset, metadata, services)
    result = validation.result
    if validation.blockers or result.structural_errors or result.requires_cleanup:
        problems = [
            *validation.blockers,
            *(
                f"строка {issue.row_position}: {issue.message}" if issue.row_position is not None else issue.message
                for issue in result.issues
            ),
        ]
        raise UploadError(
            f"dataset.csv не проходит проверку:\n{_listing(problems)}\n"
            "Исправьте или удалите эти строки; публикуются только строки без отклонений и исправлений."
        )
    if missing := missing_active_classes(bundle.dataset, metadata):
        raise UploadError(
            f"Нет ни одного bbox классов {', '.join(missing)}. Отметьте их empty: true в dataset.yaml "
            "или выгрузите данные, где они есть."
        )
    if force_resplit or parent is None:
        return
    path = services.datasets.parent_file(parent, "dataset.csv")
    if path is None:
        return
    if changes := changed_splits(bundle.dataset, published_splits(services.files.read_rows(path))):
        lines = [f"{name}: {published} → {current}" for name, published, current in changes]
        raise UploadError(
            f"Изображения опубликованы в родителе {parent.dataset_id} с другим split ({len(changes)}):\n"
            f"{_listing(lines)}\nВерните прежний split или запустите upload-dataset с --force-resplit."
        )


def _rederive_tasks(bundle: CurrentBundle) -> TaskManifest:
    """Check 6: list the tasks the current rows trace to in the archive; untraceable rows are only counted."""
    traced = trace_tasks(bundle.source.tables, bundle.dataset)
    if traced.untraced_rows:
        logger.info(
            f"{traced.untraced_rows} строк dataset.csv нельзя связать с задачами из {SOURCES_ARCHIVE}; "
            "в tasks.yaml они не попали."
        )
    return traced.manifest


def _check_parent_unchanged(
    destination: ClearMLDestination, parent: DatasetParent | None, services: BundleServices
) -> None:
    """Check 7: no compare-and-swap exists remotely, so look again after the slow checks."""
    if _identity(services.datasets.latest(destination.project, destination.dataset)) != _identity(parent):
        raise UploadError(
            f"Родитель {destination.project}/{destination.dataset} изменился во время проверок. "
            "Запустите cveta2 upload-dataset ещё раз."
        )


def upload_dataset(directory: Path, services: BundleServices, *, force_resplit: bool = False) -> Publication:
    """Publish the bundle's four current files after the checks of design 2.4, in order."""
    bundle = services.files.read_bundle(directory)
    destination = _destination(bundle)
    parent = services.datasets.latest(destination.project, destination.dataset)
    _check_recorded_parent(bundle, destination, parent)
    previous = _parent_metadata(parent, services)
    _refuse_managed(parent, previous)
    _warn_previous_publication(bundle)
    _check_classes(bundle.metadata, previous, services)
    _check_roots(bundle, destination, services)
    _check_rows(bundle, parent, services, force_resplit=force_resplit)
    tasks = _rederive_tasks(bundle)
    services.files.write_tasks(directory, tasks)
    _check_parent_unchanged(destination, parent, services)
    with services.files.stage_publication(bundle, tasks) as staged:
        publication = services.datasets.publish(
            destination.project,
            destination.dataset,
            parent.dataset_id if parent else None,
            staged,
            files=PUBLISHED_NAMES,
            output_uri=destination.output_uri,
        )
    try:
        services.files.write_publication(directory, publication, destination)
    except OSError as error:
        logger.warning(f"Датасет {publication.dataset_id} опубликован, но publication.json не записан: {error}")
    return publication

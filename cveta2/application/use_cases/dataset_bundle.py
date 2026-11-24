"""Prepare a bundle from fetch output, then publish whatever the bundle's current files make valid."""

from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd
from loguru import logger
from pydantic import ValidationError

from cveta2.application.ports.dataset_bundle import BundleServices
from cveta2.domain.bundle.classes import apply_class_marks, class_mark_changes, reconcile_classes
from cveta2.domain.bundle.draft import DatasetDraft, resolve_preparation
from cveta2.domain.bundle.models import (
    BundleValidation,
    ClassInfo,
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
from cveta2.domain.bundle.splits import changed_splits, prefill_splits, published_splits
from cveta2.domain.bundle.tasks import derive_tasks, trace_tasks
from cveta2.domain.bundle.validation import (
    TrainabilityGap,
    images_without_split,
    missing_active_classes,
    trainability_gaps,
    validate_bundle,
)
from cveta2.domain.managed.models import ClearMLDestination, hide_url_userinfo
from cveta2.domain.models import Split
from cveta2.domain.verification.models import ValidationOptions

# How many paths, rows or images one refusal lists before it only counts the rest.
_LISTED = 20
# The ``pending`` line of each training requirement that the rows with a split do not meet yet.
_GAP_PENDING: dict[TrainabilityGap, str] = {
    "train_images": "в train нет изображений",
    "val_images": "в val нет изображений",
    "train_box": "в train нет ни одного bbox",
}


# Option fields whose refused value is shown, with URL credentials hidden; no other input is echoed.
_URL_OPTIONS = frozenset({"output_uri", "api_url"})


def _option_errors(error: ValidationError) -> str:
    """Describe refused options without the credentials a refused URL may hold."""
    details = []
    for item in error.errors(include_url=False):
        field = ".".join(str(part) for part in item["loc"])
        value = item.get("input")
        shown = f" ({hide_url_userinfo(value)})" if field in _URL_OPTIONS and isinstance(value, str) else ""
        details.append(f"{field}: {item['msg']}{shown}")
    return "; ".join(details)


def _listing(items: Sequence[str]) -> str:
    """One item per line, at most ``_LISTED`` of them, then the count of the rest."""
    lines = [f"  {item}" for item in items[:_LISTED]]
    if len(items) > _LISTED:
        lines.append(f"  … и ещё {len(items) - _LISTED}")
    return "\n".join(lines)


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


def _validate(
    frame: pd.DataFrame, metadata: DatasetMetadata, services: BundleServices, *, allow_empty_split: bool = False
) -> BundleValidation:
    inspection = services.media.inspect(
        frame,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
    )
    return validate_bundle(frame, metadata, inspection=inspection, allow_empty_split=allow_empty_split)


def _parent_metadata(parent: DatasetParent | None, services: BundleServices) -> DatasetMetadata | None:
    if parent is None:
        return None
    if parent.metadata_path is None:
        raise UploadError(f"Родитель {parent.dataset_id} не содержит dataset.yaml. Выберите новое имя датасета.")
    return services.files.read_metadata(parent.metadata_path)


def _refuse_missing_files(frame: pd.DataFrame, services: BundleServices) -> None:
    if missing := services.roots.missing_files(frame):
        raise UploadError(
            f"Нет файлов изображений из image_path ({len(missing)}):\n{_listing(missing)}\n"
            "Скачайте изображения (cveta2 s3-sync) или выполните cveta2 fetch заново."
        )


def _new_destination(options: PrepareOptions, draft: DatasetDraft | None) -> ClearMLDestination:
    """Return the ClearML destination from the flags, else the draft; a missing project or name is a decision."""
    resolved = resolve_preparation(options, draft, None)
    project = resolved.project if resolved.project and resolved.project.strip() else None
    dataset = resolved.dataset_name if resolved.dataset_name and resolved.dataset_name.strip() else None
    if project is None or dataset is None:
        decisions = [Decision("project", "Укажите проект ClearML.")] if project is None else []
        if dataset is None:
            decisions.append(Decision("dataset_name", "Укажите имя датасета ClearML."))
        raise MissingDecisions(tuple(decisions))
    try:
        return ClearMLDestination(project=project, dataset=dataset, output_uri=resolved.output_uri)
    except ValidationError as error:
        # ``from None``: the chained error's text would show the refused value with its credentials.
        raise UploadError(f"Invalid preparation options: {_option_errors(error)}") from None


def _published(parent: DatasetParent | None, services: BundleServices) -> dict[str, Split] | None:
    """Return the split of each image in the parent's published ``dataset.csv``; ``None`` without that file."""
    path = services.datasets.parent_file(parent, "dataset.csv") if parent is not None else None
    return None if path is None else published_splits(services.files.read_rows(path))


def _prefill(frame: pd.DataFrame, published: Mapping[str, Split] | None) -> tuple[pd.DataFrame, int]:
    """Fill empty ``split`` cells from the parent's published splits; count the filled images."""
    return (frame, 0) if published is None else prefill_splits(frame, published)


def _api_url(value: str | None) -> str:
    if not value:
        raise MissingDecisions((Decision("api_url", "Укажите URL API классов."),))
    try:
        DatasetMetadata(api_url=value, classes={})
    except ValidationError as error:
        raise UploadError(f"Invalid preparation options or API metadata: {_option_errors(error)}") from None
    return value


def _parent_local_roots(roots: Sequence[str], services: BundleServices) -> tuple[list[str], tuple[str, ...]]:
    """Split the parent's local roots into those usable here and those missing on this machine."""
    kept: list[str] = []
    dropped: list[str] = []
    for root in roots:
        try:
            services.roots.check_local_root(root)
        except UploadError:
            dropped.append(root)
        else:
            kept.append(root)
    return kept, tuple(dropped)


def _split_missing(count: int, directory: Path) -> str:
    """Return the empty-split line that ``verify`` lists under ``pending`` and ``upload-dataset`` refuses with."""
    return f"заполните split у {count} изображений в {directory / 'dataset.csv'}"


def _pending(
    clean: pd.DataFrame, directory: Path, parent: DatasetParent | None, published: Mapping[str, Split] | None
) -> tuple[str, ...]:
    """Split conditions ``upload-dataset`` enforces that the clean rows do not meet yet."""
    if count := images_without_split(clean):
        pending = [_split_missing(count, directory)]
    else:
        pending = [_GAP_PENDING[gap] for gap in trainability_gaps(clean)]
    if parent is not None and published and (changes := changed_splits(clean, published)):
        images = len({name for name, _old, _new in changes})
        pending.append(
            f"у {images} изображений split отличается от опубликованного в родителе {parent.dataset_id}: "
            "upload-dataset откажет без --force-resplit"
        )
    return tuple(pending)


def _blockers(
    validation: BundleValidation, metadata: DatasetMetadata, options: PrepareOptions, task_error: str | None
) -> tuple[str, ...]:
    """List what keeps the payload from being written; rows that cleanup drops never block on their own."""
    blockers = list(validation.blockers)
    if task_error is not None:
        blockers.append(task_error)
    result = validation.result
    if result.requires_cleanup and not options.clean:
        blockers.append(
            f"Нужна очистка: отклонено {len(result.broken)} строк; "
            "запустите verify без --no-clean или исправьте исходные данные."
        )
    if names := missing_active_classes(result.clean, metadata):
        blockers.append(
            f"Нет ни одного bbox классов {', '.join(names)}: исключите их (--empty-class N или empty_classes в "
            "dataset.yaml выгрузки) или выгрузите данные с ними."
        )
    return tuple(blockers)


def prepare_dataset(
    source: Path, directory: Path | None, options: PrepareOptions, services: BundleServices
) -> PreparedDataset:
    """Write the bundle from the flags, the source's draft and the parent without creating a remote dataset."""
    try:
        options = PrepareOptions.model_validate(options.model_dump())
    except ValidationError as error:
        raise UploadError(f"Invalid preparation options: {_option_errors(error)}") from None
    if directory is None:
        directory = services.files.default_directory(source)
    snapshot = services.files.read_source(source)
    draft = services.files.read_draft(source)
    _refuse_missing_files(snapshot.tables.dataset, services)
    destination = _new_destination(options, draft)
    parent = services.datasets.latest(destination.project, destination.dataset)
    previous = _parent_metadata(parent, services)
    if parent is not None and previous is not None and previous.managed is not None:
        raise UploadError(
            f"Родитель {parent.dataset_id} принадлежит управляемому датасету; "
            "выберите другое имя или используйте cveta2 dataset."
        )
    # From here on ``frame`` is what is validated and written; ``snapshot`` keeps the fetched bytes.
    published = _published(parent, services)
    frame, split_prefilled = _prefill(snapshot.tables.dataset, published)
    resolved = resolve_preparation(options, draft, previous)
    api_url = _api_url(resolved.api_url)
    old_classes = previous.classes if previous else {}
    update = reconcile_classes(old_classes, services.api.fetch(api_url))
    classes = apply_class_marks(update.classes, resolved.class_marks)
    kept, dropped = _parent_local_roots(resolved.parent_local_roots, services)
    roots = _roots(
        frame, ImageRoots(local_root=[*kept, *resolved.local_roots], s3_root=list(resolved.s3_roots)), services
    )
    metadata = DatasetMetadata(clearml=destination, api_url=api_url, classes=classes, images=roots)
    validation = _validate(frame, metadata, services, allow_empty_split=True)
    task_error = None
    try:
        tasks = derive_tasks(snapshot.tables, validation.result.clean)
    except UploadError as error:
        tasks, task_error = TaskManifest(included=[], obsolete=[]), str(error)
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
            blockers=_blockers(validation, metadata, options, task_error),
            pending=_pending(validation.result.clean, directory, parent, published),
            mark_changes=class_mark_changes(old_classes, classes),
            dropped_local_roots=dropped,
            split_prefilled=split_prefilled,
        ),
    )


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
            + ". Новая публикация создаст ещё одну версию."
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
    """Check 5: splits filled, rows untouched and trainable, active classes covered, published splits kept."""
    metadata = bundle.metadata
    if count := images_without_split(bundle.dataset):
        raise UploadError(f"dataset.csv не готов к публикации:\n  {_split_missing(count, bundle.directory)}")
    # Every split is filled, so the empty-split mode differs only in leaving trainability to the lines below.
    validation = _validate(bundle.dataset, metadata, services, allow_empty_split=True)
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
    if gaps := trainability_gaps(result.clean):
        raise UploadError("dataset.csv не готов к публикации:\n" + _listing([_GAP_PENDING[gap] for gap in gaps]))
    if missing := missing_active_classes(bundle.dataset, metadata):
        raise UploadError(
            f"Нет ни одного bbox классов {', '.join(missing)}. Отметьте их empty: true в dataset.yaml "
            "или выгрузите данные, где они есть."
        )
    if force_resplit or parent is None:
        return
    if changes := changed_splits(bundle.dataset, _published(parent, services) or {}):
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
    # Before check 2: a repeated upload makes the earlier publication the latest version, and check 2 refuses it.
    _warn_previous_publication(bundle)
    _check_recorded_parent(bundle, destination, parent)
    previous = _parent_metadata(parent, services)
    _refuse_managed(parent, previous)
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

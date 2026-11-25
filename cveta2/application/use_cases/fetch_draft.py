"""Write the draft ``dataset.yaml`` of a full fetch and warn about its gaps and class coverage.

Nothing here fails the fetch: every gap, an unwritable draft and an unusable
class registry are warnings, so the CSVs already written stay the result.
"""

import shlex
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from loguru import logger
from pydantic import ValidationError

from cveta2.application.ports.dataset_bundle import ClassApi, DraftFiles
from cveta2.domain.bundle.classes import registry_classes
from cveta2.domain.bundle.draft import DatasetDraft, build_draft
from cveta2.domain.bundle.models import DatasetMetadata, UploadError
from cveta2.domain.bundle.validation import excluded_class_rows, missing_active_classes
from cveta2.domain.managed.models import PublicationSettings
from cveta2.domain.storage import CloudStorageInfo
from cveta2.domain.verification.cells import is_missing

BACKUP_NOTICE = "Прежний dataset.yaml отличался и сохранён как dataset.yaml.bak."


@dataclass(frozen=True)
class DraftServices:
    """Effects of the fetch draft: its file and the class API."""

    files: DraftFiles
    classes: ClassApi


def write_fetch_draft(  # noqa: PLR0913
    output_dir: Path,
    dataset: pd.DataFrame,
    *,
    project_name: str,
    publication: PublicationSettings | None,
    storage: CloudStorageInfo | None,
    images_dir: Path | None,
    services: DraftServices,
) -> DatasetDraft:
    """Write what the configuration and this fetch know into ``dataset.yaml``; warn, never raise."""
    draft = build_draft(publication, storage, images_dir)
    try:
        if services.files.write_draft(output_dir, draft):
            logger.warning(BACKUP_NOTICE)
    except (OSError, UploadError) as error:
        logger.warning(f"Черновик dataset.yaml не записан: {error}")
    _warn_gaps(draft, dataset, project_name)
    if draft.api_url is not None:
        _warn_coverage(draft.api_url, draft.empty_classes or [], dataset, services.classes)
    return draft


def _warn_gaps(draft: DatasetDraft, dataset: pd.DataFrame, project_name: str) -> None:
    """One warning per value the draft lacks, naming the fix."""
    if draft.api_url is None:
        logger.warning(
            f"Для проекта {project_name!r} в конфигурации нет настроек публикации: в черновике dataset.yaml "
            "нет назначения ClearML и API классов. Задайте их: "
            f"cveta2 setup --global --project {shlex.quote(project_name)} "
            "--clearml-project … --dataset-name … --api-url …, "
            "или передайте их флагами cveta2 verify (--clearml-project, --dataset-name, --api-url)."
        )
    if draft.images is None or not draft.images.local_root:
        logger.warning(
            "В черновике dataset.yaml нет локального каталога изображений (выгрузка без изображений): "
            "передайте его при подготовке — cveta2 verify --local-root <каталог>."
        )
    if "image_path" in dataset.columns:
        empty = int(dataset["image_path"].map(is_missing).sum())
        if empty:
            logger.warning(
                f"Строк dataset.csv с пустым image_path: {empty} — подготовка (cveta2 verify) остановится на них. "
                "Скачайте изображения: cveta2 s3-sync или fetch без --no-images."
            )


def _warn_coverage(api_url: str, empty_classes: list[int], dataset: pd.DataFrame, classes: ClassApi) -> None:
    """Compare the fetched labels with the current class registry; one warning if it cannot be used."""
    try:
        records = classes.fetch(api_url)
        metadata = DatasetMetadata(api_url=api_url, classes=registry_classes(records, empty_classes))
        excluded = excluded_class_rows(dataset, metadata)
        missing = missing_active_classes(dataset, metadata)
    except UploadError as error:
        logger.warning(f"Проверка классов по {api_url} пропущена: {error}")
        return
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        logger.warning(f"Проверка классов по {api_url} пропущена: {details}")
        return
    unknown = sorted(set(empty_classes) - {record.number for record in records})
    if unknown:
        logger.warning(
            f"Номеров классов {unknown} из empty_classes нет в реестре классов (опечатка или удалённый класс?): "
            "cveta2 verify остановится на них."
        )
    if excluded:
        logger.warning(
            f"Строк dataset.csv с исключёнными классами (empty: true): {excluded} — "
            "cveta2 verify отбросит их при очистке."
        )
    if missing:
        logger.warning(
            f"Классы без единого bbox в dataset.csv: {', '.join(missing)}. Добавьте данные с ними "
            "или отметьте их empty: true (номер класса в empty_classes черновика dataset.yaml), "
            "иначе cveta2 verify остановится."
        )

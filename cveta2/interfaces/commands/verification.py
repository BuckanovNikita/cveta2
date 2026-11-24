"""Russian CLI presentation for the CSV check, bundle preparation and bundle publication."""

import argparse
import sys
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from cveta2.composition.configuration import is_interactive_disabled
from cveta2.domain.bundle.models import ClassChange, UploadCancelled
from cveta2.domain.bundle.preparation import MissingDecisions, PreparedDataset, PrepareOptions
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.verification.models import ValidationOptions, ValidationResult
from cveta2.interfaces.commands.interactive.bundle import collect_decisions
from cveta2.interfaces.datasets import prepare_dataset, upload_dataset, verify


def configure_verify(parser: argparse.ArgumentParser) -> None:
    """Declare the CSV check and the bundle preparation of a full fetch directory."""
    parser.add_argument(
        "input",
        help="CSV-файл для проверки или каталог полной выгрузки для подготовки набора.",
    )
    csv_check = parser.add_argument_group("проверка CSV")
    csv_check.add_argument(
        "--profile",
        choices=("cveta2", "clearml-yolo"),
        default="cveta2",
        help="Профиль проверки CSV.",
    )
    csv_check.add_argument(
        "--check-images",
        action="store_true",
        help="Декодировать локальные изображения.",
    )
    csv_check.add_argument("--image-root", type=Path, help="Каталог для пустых image_path.")
    csv_check.add_argument(
        "--iou-threshold",
        type=float,
        default=0.99,
        help="Порог поиска дубликатов (0, 1].",
    )
    cleanup = parser.add_mutually_exclusive_group()
    cleanup.add_argument(
        "--clean",
        action="store_true",
        help="Разрешить исправления и удаление отклонённых строк (для CSV требует --output-dir; "
        "при подготовке включено по умолчанию).",
    )
    cleanup.add_argument(
        "--no-clean",
        action="store_true",
        help="Подготовка: не убирать отклонённые строки; если они есть, набор не готовится.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Новый каталог отчёта CSV или подготовленного набора (по умолчанию <каталог>-prepared).",
    )
    preparation = parser.add_argument_group("подготовка каталога")
    preparation.add_argument("--clearml-project", help="Проект ClearML.")
    preparation.add_argument("--dataset-name", help="Имя набора ClearML.")
    preparation.add_argument("--output-uri", help="Куда ClearML загружает файлы набора.")
    preparation.add_argument("--api-url", help="Публичный HTTP(S) API классов.")
    preparation.add_argument(
        "--local-root",
        action="append",
        default=[],
        help="Разрешённый локальный каталог; можно повторять.",
    )
    preparation.add_argument(
        "--s3-root",
        action="append",
        default=[],
        help="Разрешённый s3://bucket/prefix; можно повторять.",
    )
    preparation.add_argument(
        "--empty-class",
        type=int,
        action="append",
        default=[],
        help="Номер API класса для исключения; можно повторять.",
    )
    preparation.add_argument(
        "--include-class",
        type=int,
        action="append",
        default=[],
        help="Номер класса, исключённого в родителе, который надо вернуть; можно повторять.",
    )
    preparation.add_argument(
        "--non-interactive",
        action="store_true",
        help="Не запрашивать недостающие решения.",
    )


def configure_upload_dataset(parser: argparse.ArgumentParser) -> None:
    """Accept a prepared directory and the one override of the split rule."""
    parser.add_argument(
        "prepared_dir",
        type=Path,
        help="Каталог, подготовленный cveta2 verify.",
    )
    parser.add_argument(
        "--force-resplit",
        action="store_true",
        help="Разрешить другой split у изображений, уже опубликованных в родителе.",
    )


def _summary(result: ValidationResult) -> None:
    logger.info(
        f"Проверка: {result.input_row_count} строк; допустимых {len(result.clean)}, отклонённых {len(result.broken)}."
    )
    for issue in result.issues:
        row = f" строка {issue.row_position}" if issue.row_position is not None else ""
        logger.info(f"{issue.code}{row}: {issue.message}")


# Destinations of the flags that only a full fetch directory takes.
_PREPARATION_FLAGS = (
    "clearml_project",
    "dataset_name",
    "output_uri",
    "api_url",
    "local_root",
    "s3_root",
    "empty_class",
    "include_class",
    "no_clean",
)


def _prepare_options(args: argparse.Namespace) -> PrepareOptions:
    if args.check_images or args.image_root is not None or args.iou_threshold != ValidationOptions().iou_threshold:
        raise Cveta2Error(
            "Параметры --check-images, --image-root и изменённый --iou-threshold "
            "относятся к проверке CSV; подготовка каталога всегда проверяет изображения."
        )
    if both := sorted(set(args.empty_class) & set(args.include_class)):
        raise Cveta2Error(f"Класс {both[0]} указан и в --empty-class, и в --include-class.")
    return PrepareOptions(
        project=args.clearml_project,
        dataset_name=args.dataset_name,
        output_uri=args.output_uri,
        api_url=args.api_url,
        local_roots=tuple(args.local_root),
        s3_roots=tuple(args.s3_root),
        class_empty={**dict.fromkeys(args.empty_class, True), **dict.fromkeys(args.include_class, False)},
        clean=not args.no_clean,
    )


def _class_change(change: ClassChange) -> str:
    if change.kind == "renamed":
        return f"Класс переименован: {change.prod_id} {change.old_name} → {change.name}"
    return f"Класс добавлен: {change.prod_id} {change.name}"


def _broken_images(result: PreparedDataset) -> str | None:
    """Name ``broken-images.csv`` and what it holds, so dropped rows are noticed even on success."""
    broken = result.validation.broken_images
    if broken.empty:
        return None
    path = result.directory / "broken-images.csv"
    if "image_name" not in broken:
        return f"В broken-images.csv записано {len(broken)} строк: {path}"
    images = broken["image_name"].nunique()
    return f"В broken-images.csv записано {len(broken)} строк {images} изображений с отклонёнными строками: {path}"


def _report_preparation(result: PreparedDataset) -> None:
    _summary(result.validation.result)
    if result.split_prefilled:
        logger.info(f"split заполнен из родителя у {result.split_prefilled} изображений")
    if result.parent is None:
        # Without a parent every registry class counts as added: one line instead of one per class.
        classes = result.metadata.classes.values()
        excluded = sum(info.empty for info in classes)
        logger.info(f"Родительской версии нет: {len(classes)} классов из API, исключено {excluded}")
    else:
        for change in result.changes:
            logger.info(_class_change(change))
    for mark in result.mark_changes:
        logger.info(f"Класс {mark.prod_id} {mark.name} {'исключён' if mark.empty else 'возвращён'}")
    for root in result.dropped_local_roots:
        logger.info(f"Корень родителя {root} не найден на этой машине и не перенесён")
    if broken := _broken_images(result):
        logger.info(broken)
    for blocker in result.blockers:
        logger.info(blocker)
    if not result.ready:
        logger.info(f"Набор не подготовлен; отчёт: {result.directory / 'report.json'}")
        raise SystemExit(1)
    logger.info(f"Набор подготовлен: {result.directory}")
    for item in result.pending:
        logger.info(f"Перед публикацией: {item}")
    logger.info(f"Затем: cveta2 upload-dataset {result.directory}")


def _prepare(args: argparse.Namespace) -> None:
    options = _prepare_options(args)
    while True:
        try:
            result = prepare_dataset(args.input, output_dir=args.output_dir, options=options)
            break
        except MissingDecisions as error:
            if args.non_interactive or is_interactive_disabled() or not sys.stdin.isatty():
                raise
            options = collect_decisions(options, error.decisions)
    _report_preparation(result)


def _validate_csv_arguments(args: argparse.Namespace) -> None:
    # A mistyped directory is not a directory either: name the missing path before judging the flags.
    if not Path(args.input).exists():
        raise Cveta2Error(f"Нет такого файла или каталога: {args.input}")
    if any(getattr(args, name) for name in _PREPARATION_FLAGS):
        raise Cveta2Error("Настройки подготовки относятся к каталогу полной выгрузки.")
    if args.clean and args.output_dir is None:
        raise Cveta2Error("Для --clean требуется --output-dir.")


def run_verify(args: argparse.Namespace) -> None:
    """Prepare a bundle from a directory, else check a CSV; findings exit one, operational errors two."""
    try:
        if Path(args.input).is_dir():
            _prepare(args)
            return
        _validate_csv_arguments(args)
        result = verify(
            args.input,
            profile=args.profile,
            options=ValidationOptions(
                check_images=args.check_images,
                image_root=args.image_root,
                iou_threshold=args.iou_threshold,
                emit_warnings=False,
            ),
            output_dir=args.output_dir,
            clean=args.clean,
        )
        _summary(result)
        if result.structural_errors or (result.requires_cleanup and not args.clean):
            raise SystemExit(1)
    except (KeyboardInterrupt, UploadCancelled):
        logger.info("Проверка отменена.")
        raise SystemExit(1) from None
    except (Cveta2Error, ValidationError, OSError) as error:
        logger.info(f"Ошибка проверки: {error}")
        raise SystemExit(2) from error


def run_upload_dataset(args: argparse.Namespace) -> None:
    """Report success only after the adapter proves remote finalization."""
    try:
        result = upload_dataset(args.prepared_dir, force_resplit=args.force_resplit)
        logger.info(f"Опубликован датасет {result.dataset_id}, версия {result.version or 'назначена сервером'}.")
    except (KeyboardInterrupt, UploadCancelled) as error:
        logger.info(f"Публикация отменена: {error}")
        raise SystemExit(1) from error
    except (Cveta2Error, ValidationError, OSError) as error:
        logger.info(f"Ошибка публикации: {error}")
        raise SystemExit(2) from error

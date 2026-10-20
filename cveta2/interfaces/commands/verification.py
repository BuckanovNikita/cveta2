"""Russian CLI presentation for verification and explicit bundle publication."""

import argparse
import sys
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from cveta2.composition.configuration import is_interactive_disabled
from cveta2.domain.bundle.models import UploadCancelled
from cveta2.domain.bundle.preparation import MissingDecisions, PrepareOptions
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.verification.models import ValidationOptions, ValidationResult
from cveta2.interfaces.commands.interactive.bundle import collect_decisions
from cveta2.interfaces.datasets import prepare_dataset, upload_dataset, verify


def configure_verify(parser: argparse.ArgumentParser) -> None:
    """Declare explicit validation and preparation inputs."""
    parser.add_argument("input", help="CSV или каталог полного fetch для --bundle.")
    parser.add_argument(
        "--profile",
        choices=("cveta2", "clearml-yolo"),
        default="cveta2",
        help="Профиль проверки CSV.",
    )
    parser.add_argument(
        "--check-images",
        action="store_true",
        help="Декодировать локальные изображения.",
    )
    parser.add_argument(
        "--image-root", type=Path, help="Каталог для пустых image_path."
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=0.99,
        help="Порог поиска дубликатов (0, 1].",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Явно разрешить исправления и удаление отклонённых строк.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Новый каталог отчёта или подготовленного набора.",
    )
    parser.add_argument(
        "--bundle",
        action="store_true",
        help="Подготовить полный набор для последующего upload-dataset.",
    )
    parser.add_argument("--project", help="Проект ClearML (только --bundle).")
    parser.add_argument("--dataset-name", help="Имя набора ClearML.")
    parser.add_argument("--api-url", help="Публичный HTTP(S) API классов.")
    parser.add_argument(
        "--local-root",
        action="append",
        default=[],
        help="Разрешённый локальный каталог; можно повторять.",
    )
    parser.add_argument(
        "--s3-root",
        action="append",
        default=[],
        help="Разрешённый s3://bucket/prefix; можно повторять.",
    )
    parser.add_argument(
        "--empty-class",
        type=int,
        action="append",
        default=[],
        help="Номер API класса для исключения; можно повторять.",
    )
    parser.add_argument(
        "--accept-default-classes",
        action="store_true",
        help="Новые классы по умолчанию не исключаются.",
    )
    parser.add_argument(
        "--accept-class-changes",
        action="store_true",
        help="Подтвердить добавления и переименования классов родителя.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Не запрашивать недостающие решения.",
    )


def configure_upload_dataset(parser: argparse.ArgumentParser) -> None:
    """Accept only a prepared local directory, never mutable source options."""
    parser.add_argument(
        "prepared_dir",
        type=Path,
        help="Каталог с preparation.json, созданный verify --bundle.",
    )


def _summary(result: ValidationResult) -> None:
    logger.info(
        f"Проверка: {result.input_row_count} строк; "
        f"допустимых {len(result.clean)}, отклонённых {len(result.broken)}."
    )
    for issue in result.issues:
        row = f" строка {issue.row_position}" if issue.row_position is not None else ""
        logger.info(f"{issue.code}{row}: {issue.message}")


def _prepare(args: argparse.Namespace) -> None:
    if not args.project:
        raise Cveta2Error("Для --bundle укажите --project.")
    if (
        args.check_images
        or args.image_root is not None
        or args.iou_threshold != ValidationOptions().iou_threshold
    ):
        raise Cveta2Error(
            "Параметры --check-images, --image-root и изменённый --iou-threshold "
            "относятся к проверке CSV; bundle всегда проверяет изображения."
        )
    options = PrepareOptions(
        project=args.project,
        dataset_name=args.dataset_name,
        api_url=args.api_url,
        local_roots=tuple(args.local_root),
        s3_roots=tuple(args.s3_root),
        class_empty=dict.fromkeys(args.empty_class, True),
        accept_default_classes=args.accept_default_classes,
        accept_class_changes=args.accept_class_changes,
        clean=args.clean,
    )
    while True:
        try:
            result = prepare_dataset(
                args.input, output_dir=args.output_dir, options=options
            )
            break
        except MissingDecisions as error:
            if (
                args.non_interactive
                or is_interactive_disabled()
                or not sys.stdin.isatty()
            ):
                raise
            options = collect_decisions(options, error.decisions)
    _summary(result.validation.result)
    for blocker in result.validation.blockers:
        logger.info(blocker)
    logger.info(f"Отчёт: {result.directory}")
    if not result.ready:
        logger.info(
            "Набор не готов к публикации; исправьте исходные данные "
            "или явно разрешите очистку."
        )
        raise SystemExit(1)
    logger.info(
        f"Набор подготовлен. После проверки: cveta2 upload-dataset {result.directory}"
    )


def _validate_arguments(args: argparse.Namespace) -> None:
    if (args.clean or args.bundle) and args.output_dir is None:
        raise Cveta2Error("Для --clean и --bundle требуется --output-dir.")
    if not args.bundle and (
        args.project
        or args.dataset_name
        or args.api_url
        or args.local_root
        or args.s3_root
        or args.empty_class
        or args.accept_default_classes
        or args.accept_class_changes
    ):
        raise Cveta2Error("Настройки публикации требуют --bundle.")


def run_verify(args: argparse.Namespace) -> None:
    """Map findings to status one and operational/input errors to status two."""
    try:
        _validate_arguments(args)
        if args.bundle:
            _prepare(args)
            return
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
        result = upload_dataset(args.prepared_dir)
        logger.info(
            f"Опубликован датасет {result.dataset_id}, "
            f"версия {result.version or 'назначена сервером'}."
        )
    except (KeyboardInterrupt, UploadCancelled) as error:
        logger.info(f"Публикация отменена: {error}")
        raise SystemExit(1) from error
    except (Cveta2Error, ValidationError, OSError) as error:
        logger.info(f"Ошибка публикации: {error}")
        raise SystemExit(2) from error

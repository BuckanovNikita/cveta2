"""Russian presentation for managed dataset operations and shared selection."""

import argparse
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext, redirect_stdout
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from cveta2.composition.runtime import cli_external_failures
from cveta2.domain.errors import Cveta2Error
from cveta2.interfaces import managed_datasets
from cveta2.interfaces.commands._helpers import global_config_from_args
from cveta2.interfaces.commands._parsers import add_global_config_arg


def configure_managed(parser: argparse.ArgumentParser) -> None:
    """Declare the managed group without mapping override flags."""
    commands = parser.add_subparsers(dest="dataset_operation", required=True)
    for operation in (
        "list",
        "show",
        "versions",
        "fetch",
        "prepare",
        "diff",
        "report-errors",
        "publish",
    ):
        command = commands.add_parser(operation)
        command.add_argument("--config", type=Path, help="Личный файл конфигурации.")
        add_global_config_arg(command)
        command.add_argument("--json", action="store_true", help="Вывести только JSON в stdout, сообщения — в stderr.")
        if operation in {"show", "versions", "fetch", "prepare"}:
            command.add_argument("name", help="Имя набора из общего файла.")
        if operation in {"fetch", "prepare"}:
            command.add_argument("--output-dir", type=Path, required=True)
        if operation == "fetch":
            command.add_argument("--refresh", action="store_true", help="Прочитать аннотации заново.")
        if operation == "prepare":
            command.add_argument("csv", type=Path, help="CSV после пользовательского преобразования.")
            command.add_argument(
                "--source",
                type=Path,
                required=True,
                help="Каталог полного managed fetch.",
            )
            cleanup = command.add_mutually_exclusive_group()
            cleanup.add_argument(
                "--clean",
                action="store_true",
                dest="clean",
                default=True,
                help="Оставлено для совместимости: очистка включена по умолчанию.",
            )
            cleanup.add_argument(
                "--no-clean",
                action="store_false",
                dest="clean",
                help="Не удалять отклонённые строки: подготовка остановится, если очистка нужна.",
            )
            command.add_argument(
                "--first",
                action="store_true",
                help="Начать управляемую историю: последнюю версию без managed не использовать.",
            )
        if operation == "diff":
            command.add_argument("old", help="Каталог/CSV или ID версии ClearML.")
            command.add_argument("new", help="Каталог/CSV или ID версии ClearML.")
        if operation in {"report-errors", "publish"}:
            command.add_argument("prepared", type=Path, help="Каталог проверенной подготовки.")
        if operation == "publish":
            command.add_argument(
                "--force-resplit",
                action="store_true",
                help=(
                    "Разрешить split, отличный от опубликованного в родительской версии; "
                    "опубликованные назначения заменятся значениями из dataset.csv."
                ),
            )


def run_managed(args: argparse.Namespace) -> None:
    """Report operational failures with exit code 2, distinct from an unready preparation."""
    try:
        # Translate SDK exceptions before assigning the managed operation's exit status.
        sdk_output = _sdk_output_to_stderr() if args.json else nullcontext()
        with sdk_output, cli_external_failures():
            result, status = _dispatch(args)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (Cveta2Error, ValidationError, OSError) as error:
        logger.error(f"Ошибка операции с набором данных: {error}")
        raise SystemExit(2) from error
    if status:
        raise SystemExit(status)


@contextmanager
def _sdk_output_to_stderr() -> Iterator[None]:
    """Route SDK progress, including handlers bound to fd 1 before dispatch."""
    sys.stdout.flush()
    with os.fdopen(os.dup(1), "wb") as original_stdout:
        os.dup2(2, 1)
        try:
            with redirect_stdout(sys.stderr):
                yield
        finally:
            try:
                sys.stdout.flush()
            finally:
                os.dup2(original_stdout.fileno(), 1)


def _dispatch(args: argparse.Namespace) -> tuple[object, int]:
    """Dispatch typed public operations; APIs never prompt."""
    options = {"config_path": args.config, "project_config": global_config_from_args(args)}
    result: object
    operation = args.dataset_operation
    if operation == "list":
        result = managed_datasets.list_datasets(**options)
    elif operation == "show":
        result = managed_datasets.show_dataset(args.name, **options)
    elif operation == "versions":
        result = managed_datasets.dataset_versions(args.name, **options)
    elif operation == "fetch":
        result = managed_datasets.fetch_dataset(args.name, output_dir=args.output_dir, refresh=args.refresh, **options)
    elif operation == "prepare":
        prepared = managed_datasets.prepare_managed_dataset(
            args.name,
            args.csv,
            source=args.source,
            output_dir=args.output_dir,
            clean=args.clean,
            first=args.first,
            **options,
        )
        return prepared.model_dump(mode="json"), 0 if prepared.ready else 1
    elif operation == "diff":
        result = managed_datasets.compare_datasets(args.old, args.new, **options)
    elif operation == "report-errors":
        report = managed_datasets.report_dataset_errors(args.prepared, **options)
        return report.model_dump(mode="json"), 2 if report.failed else 0
    else:
        publication = managed_datasets.publish_dataset(args.prepared, force_resplit=args.force_resplit, **options)
        result = {"dataset_id": publication.dataset_id, "version": publication.version}
    return result, 0

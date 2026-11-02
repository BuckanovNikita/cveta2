"""Russian presentation for managed dataset operations and shared selection."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from cveta2.interfaces import managed_datasets


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
        command.add_argument(
            "--project-config", type=Path, help="Общий файл проектов и сопоставлений."
        )
        command.add_argument(
            "--json", action="store_true", help="Вывести результат в JSON."
        )
        if operation in {"show", "versions", "fetch", "prepare"}:
            command.add_argument("name", help="Имя набора из общего файла.")
        if operation in {"fetch", "prepare"}:
            command.add_argument("--output-dir", type=Path, required=True)
        if operation == "fetch":
            command.add_argument(
                "--refresh", action="store_true", help="Прочитать аннотации заново."
            )
        if operation == "prepare":
            command.add_argument(
                "csv", type=Path, help="CSV после пользовательского преобразования."
            )
            command.add_argument(
                "--source",
                type=Path,
                required=True,
                help="Каталог полного managed fetch.",
            )
            command.add_argument(
                "--clean",
                action="store_true",
                help="Принять исправления и удаление отклонённых строк.",
            )
        if operation == "diff":
            command.add_argument("old", help="Каталог/CSV или ID версии ClearML.")
            command.add_argument("new", help="Каталог/CSV или ID версии ClearML.")
        if operation in {"report-errors", "publish"}:
            command.add_argument(
                "prepared", type=Path, help="Каталог проверенной подготовки."
            )


def run_managed(args: argparse.Namespace) -> None:
    """Dispatch typed public operations; APIs never prompt."""
    options = {"config_path": args.config, "project_config": args.project_config}
    result: Any
    operation = args.dataset_operation
    if operation == "list":
        result = managed_datasets.list_datasets(**options)
    elif operation == "show":
        result = managed_datasets.show_dataset(args.name, **options)
    elif operation == "versions":
        result = managed_datasets.dataset_versions(args.name, **options)
    elif operation == "fetch":
        result = managed_datasets.fetch_dataset(
            args.name, output_dir=args.output_dir, refresh=args.refresh, **options
        )
    elif operation == "prepare":
        prepared = managed_datasets.prepare_managed_dataset(
            args.name,
            args.csv,
            source=args.source,
            output_dir=args.output_dir,
            clean=args.clean,
            **options,
        )
        result = prepared.model_dump(mode="json")
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        if not prepared.ready:
            raise SystemExit(1)
        return
    elif operation == "diff":
        result = managed_datasets.compare_datasets(args.old, args.new, **options)
    elif operation == "report-errors":
        result = managed_datasets.report_dataset_errors(
            args.prepared, **options
        ).model_dump(mode="json")
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        if result["failed"]:
            raise SystemExit(2)
        return
    else:
        result = managed_datasets.publish_dataset(args.prepared, **options)
        result = {"dataset_id": result.dataset_id, "version": result.version}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

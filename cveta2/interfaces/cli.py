"""CLI entry point for cveta2."""

import argparse
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from cveta2.domain.errors import Cveta2Error
from cveta2.interfaces.commands._parsers import add_config_arg
from cveta2.interfaces.commands.convert import configure_convert, run_convert
from cveta2.interfaces.commands.doctor import configure_doctor, run_doctor
from cveta2.interfaces.commands.fetch import (
    configure_fetch,
    configure_fetch_task,
    run_fetch,
    run_fetch_task,
)
from cveta2.interfaces.commands.ignore import configure_ignore, run_ignore
from cveta2.interfaces.commands.labels import configure_labels, run_labels
from cveta2.interfaces.commands.merge import configure_merge, run_merge
from cveta2.interfaces.commands.s3_sync import configure_s3_sync, run_s3_sync
from cveta2.interfaces.commands.setup import (
    configure_setup_cache,
    run_setup,
    run_setup_cache,
)
from cveta2.interfaces.commands.task_ops import (
    configure_task_delete,
    configure_task_drop_label,
    configure_task_mark_deleted,
    configure_task_status,
    run_task_delete,
    run_task_drop_label,
    run_task_mark_deleted,
    run_task_status,
)
from cveta2.interfaces.commands.upload import configure_upload, run_upload
from cveta2.interfaces.commands.verification import (
    configure_upload_dataset,
    configure_verify,
    run_upload_dataset,
    run_verify,
)
from cveta2.interfaces.commands.whats_new import configure_whats_new, run_whats_new

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One CLI subcommand: name, help, argument wiring and handler."""

    name: str
    help: str
    handler: "Callable[[argparse.Namespace], None] | None" = None
    configure: "Callable[[argparse.ArgumentParser], None] | None" = None
    subcommands: "tuple[CommandSpec, ...]" = ()


def _command_specs() -> "tuple[CommandSpec, ...]":
    """Build the command registry.

    Built at call time (inside ``CliApp.__init__``) so that tests
    patching ``cveta2.interfaces.cli.run_*`` see their mocks captured.
    """
    return (
        CommandSpec(
            "verify",
            "Проверить CSV или подготовить набор.",
            run_verify,
            configure_verify,
        ),
        CommandSpec(
            "upload-dataset",
            "Опубликовать проверенный набор в ClearML.",
            run_upload_dataset,
            configure_upload_dataset,
        ),
        CommandSpec(
            "fetch",
            "Fetch all project bbox annotations and deleted images.",
            run_fetch,
            configure_fetch,
        ),
        CommandSpec(
            "fetch-task",
            "Fetch bbox annotations for specific task(s) in a project.",
            run_fetch_task,
            configure_fetch_task,
        ),
        CommandSpec(
            "setup",
            "Interactively configure CVAT connection settings.",
            run_setup,
            add_config_arg,
        ),
        CommandSpec(
            "setup-cache",
            "Interactively configure image cache directories for all projects.",
            run_setup_cache,
            configure_setup_cache,
        ),
        CommandSpec(
            "s3-sync",
            "Sync images from S3 cloud storage to local cache for every "
            "project configured under image_cache or cache.projects.",
            run_s3_sync,
            configure_s3_sync,
        ),
        CommandSpec(
            "upload",
            "Create a CVAT task from dataset.csv: filter classes, "
            "upload images to S3, create task with cloud storage.",
            run_upload,
            configure_upload,
        ),
        CommandSpec(
            "merge",
            "Merge two dataset CSV files. For images in both, new annotations win.",
            run_merge,
            configure_merge,
        ),
        CommandSpec(
            "ignore",
            "Manage the per-project ignore list of tasks "
            "(always treated as in-progress during fetch).",
            run_ignore,
            configure_ignore,
        ),
        CommandSpec(
            "labels",
            "List and interactively edit project labels. "
            "Includes safety checks before label deletion.",
            run_labels,
            configure_labels,
        ),
        CommandSpec(
            "convert",
            "Convert between cveta2 CSV and YOLO/COCO detection formats.",
            run_convert,
            configure_convert,
        ),
        CommandSpec(
            "task",
            "Task write operations: mark-deleted, drop-label, delete, status.",
            subcommands=(
                CommandSpec(
                    "mark-deleted",
                    "Mark task frames as deleted by frame ID and/or image name.",
                    run_task_mark_deleted,
                    configure_task_mark_deleted,
                ),
                CommandSpec(
                    "drop-label",
                    "Delete all annotations with the given label from a task.",
                    run_task_drop_label,
                    configure_task_drop_label,
                ),
                CommandSpec(
                    "delete",
                    "Delete a task permanently.",
                    run_task_delete,
                    configure_task_delete,
                ),
                CommandSpec(
                    "status",
                    "Set stage and/or state for all jobs of a task.",
                    run_task_status,
                    configure_task_status,
                ),
            ),
        ),
        CommandSpec(
            "doctor",
            "Check configuration and cache health.",
            run_doctor,
            configure_doctor,
        ),
        CommandSpec(
            "whats-new",
            "List tasks completed after the tasks in a fetched dataset CSV.",
            run_whats_new,
            configure_whats_new,
        ),
    )


def _register(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
    spec: "CommandSpec",
) -> None:
    """Register one command spec (and its nested subcommands) on *subparsers*."""
    parser = subparsers.add_parser(spec.name, help=spec.help)
    if spec.configure is not None:
        spec.configure(parser)
    if spec.subcommands:
        nested = parser.add_subparsers(dest="action", required=True)
        for sub in spec.subcommands:
            _register(nested, sub)
    else:
        parser.set_defaults(handler=spec.handler)


class CliApp:
    """Command-line interface for cveta2."""

    def __init__(self) -> None:
        """Initialize parser and command definitions."""
        self._parser = self._build_parser()

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="CVAT project utilities.",
        )
        subparsers = parser.add_subparsers(dest="command", required=True)
        for spec in _command_specs():
            _register(subparsers, spec)
        return parser

    def _run_command(self, args: argparse.Namespace) -> None:
        """Dispatch parsed args to the target command implementation.

        Domain errors (:class:`Cveta2Error`) raised by any command surface
        here as a clean ``sys.exit`` message, so individual commands never
        embed exit plumbing.
        """
        handler: Callable[[argparse.Namespace], None] = args.handler
        try:
            handler(args)
        except Cveta2Error as e:
            sys.exit(str(e))
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors(include_input=False, include_url=False)
            )
            sys.exit(
                f"Некорректная конфигурация: {details}. "
                f"Проверьте YAML и переменные окружения."
            )

    def run(self, argv: list[str] | None = None) -> None:
        """Run the CLI with the given arguments."""
        args = self._parser.parse_args(argv)
        self._run_command(args)


def main(argv: list[str] | None = None) -> None:
    """Compatibility entry point for setuptools/CLI wrappers."""
    CliApp().run(argv)


if __name__ == "__main__":
    main()

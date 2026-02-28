"""CLI entry point for cveta2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from cveta2.commands.doctor import run_doctor

if TYPE_CHECKING:
    from collections.abc import Callable
from cveta2.commands.fetch import run_fetch, run_fetch_task
from cveta2.commands.ignore import run_ignore
from cveta2.commands.labels import run_labels
from cveta2.commands.merge import run_merge
from cveta2.commands.s3_sync import run_s3_sync
from cveta2.commands.setup import run_setup, run_setup_cache
from cveta2.commands.upload import run_upload
from cveta2.config import get_config_path


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

        self._add_fetch_parser(subparsers)
        self._add_fetch_task_parser(subparsers)
        self._add_setup_parser(subparsers)
        self._add_setup_cache_parser(subparsers)
        self._add_s3_sync_parser(subparsers)
        self._add_upload_parser(subparsers)
        self._add_merge_parser(subparsers)
        self._add_ignore_parser(subparsers)
        self._add_labels_parser(subparsers)
        self._add_doctor_parser(subparsers)

        return parser

    def _add_fetch_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``fetch`` command parser."""
        parser = subparsers.add_parser(
            "fetch",
            help="Fetch all project bbox annotations and deleted images.",
        )
        parser.add_argument(
            "--project",
            "-p",
            type=str,
            default=None,
            help=(
                "Project ID or name. If omitted, "
                "interactive project selection is shown."
            ),
        )
        parser.add_argument(
            "--output-dir",
            "-o",
            required=True,
            help="Directory to save partitioned CSV files "
            "(dataset, obsolete, in_progress, deleted).",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Save all records (including deletions) "
            "as raw.csv without partitioning.",
        )
        self._add_common_fetch_args(parser)

    def _add_fetch_task_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``fetch-task`` command parser."""
        parser = subparsers.add_parser(
            "fetch-task",
            help="Fetch bbox annotations for specific task(s) in a project.",
        )
        parser.add_argument(
            "--project",
            "-p",
            type=str,
            default=None,
            help=(
                "Project ID or name. If omitted, "
                "interactive project selection is shown."
            ),
        )
        parser.add_argument(
            "--task",
            "-t",
            type=str,
            nargs="?",
            const="",
            action="append",
            default=None,
            help=(
                "Task ID or name to fetch. "
                "Can be repeated: -t 42 -t 43. "
                "If passed without a value (-t), interactive "
                "multi-select is shown."
            ),
        )
        parser.add_argument(
            "--output-dir",
            "-o",
            required=True,
            help="Directory to save dataset.csv and deleted.csv.",
        )
        self._add_common_fetch_args(parser)

    @staticmethod
    def _add_common_fetch_args(parser: argparse.ArgumentParser) -> None:
        """Add arguments shared between ``fetch`` and ``fetch-task``."""
        parser.add_argument(
            "--completed-only",
            action="store_true",
            help="Process only tasks with status 'completed'.",
        )
        parser.add_argument(
            "--no-images",
            action="store_true",
            help="Skip downloading images from S3 cloud storage.",
        )
        parser.add_argument(
            "--images-dir",
            type=str,
            default=None,
            help=(
                "Override image cache directory for this run "
                "(takes precedence over config mapping)."
            ),
        )
        parser.add_argument(
            "--save-tasks",
            action="store_true",
            help=(
                "Keep per-task CSV files in .tasks/ subdirectory. "
                "By default they are removed after merging."
            ),
        )

    def _add_setup_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``setup`` command parser."""
        parser = subparsers.add_parser(
            "setup",
            help="Interactively configure CVAT connection settings.",
        )
        parser.add_argument(
            "--config",
            default=None,
            help=(
                "Path to YAML config (default: ~/.config/cveta2/config.yaml "
                "or CVETA2_CONFIG)."
            ),
        )

    def _add_setup_cache_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``setup-cache`` command parser."""
        parser = subparsers.add_parser(
            "setup-cache",
            help="Interactively configure image cache directories for all projects.",
        )
        parser.add_argument(
            "--config",
            default=None,
            help=(
                "Path to YAML config (default: ~/.config/cveta2/config.yaml "
                "or CVETA2_CONFIG)."
            ),
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Re-ask path for every project using cache_root/project_name "
                "as default (ignore existing paths)."
            ),
        )
        parser.add_argument(
            "--list",
            dest="list_paths",
            action="store_true",
            help="List current image cache paths and exit.",
        )

    def _add_s3_sync_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``s3-sync`` command parser."""
        parser = subparsers.add_parser(
            "s3-sync",
            help=(
                "Sync images from S3 cloud storage to local cache "
                "for all configured projects."
            ),
        )
        parser.add_argument(
            "--project",
            "-p",
            type=str,
            default=None,
            help=(
                "Sync only this project (name from image_cache config). "
                "If omitted, syncs every configured project."
            ),
        )

    def _add_upload_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``upload`` command parser."""
        parser = subparsers.add_parser(
            "upload",
            help=(
                "Create a CVAT task from dataset.csv: filter classes, "
                "upload images to S3, create task with cloud storage."
            ),
        )
        parser.add_argument(
            "--project",
            "-p",
            type=str,
            default=None,
            help=(
                "Project ID or name. If omitted, "
                "interactive project selection is shown."
            ),
        )
        parser.add_argument(
            "--dataset",
            "-d",
            required=True,
            help="Path to dataset.csv produced by the fetch command.",
        )
        parser.add_argument(
            "--in-progress",
            type=str,
            default=None,
            help=(
                "Path to in_progress.csv — images listed there "
                "will be excluded from the upload."
            ),
        )
        parser.add_argument(
            "--image-dir",
            type=str,
            default=None,
            help="Additional directory to search for image files.",
        )
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="Task name. If omitted, prompted interactively.",
        )
        parser.add_argument(
            "--complete",
            action="store_true",
            help="Mark the task as completed after upload.",
        )

    def _add_merge_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``merge`` command parser."""
        parser = subparsers.add_parser(
            "merge",
            help=(
                "Merge two dataset CSV files. For images in both, new annotations win."
            ),
        )
        parser.add_argument(
            "--old",
            required=True,
            help="Path to the old (base) dataset CSV.",
        )
        parser.add_argument(
            "--new",
            required=True,
            help="Path to the new dataset CSV.",
        )
        parser.add_argument(
            "--deleted",
            type=str,
            default=None,
            help=(
                "Path to deleted.csv — images listed there "
                "will be removed from the merged result."
            ),
        )
        parser.add_argument(
            "--output",
            "-o",
            required=True,
            help="Path for the merged output CSV.",
        )
        parser.add_argument(
            "--by-time",
            action="store_true",
            help=(
                "Resolve conflicts by task_updated_date instead "
                "of argument order (requires task_updated_date column)."
            ),
        )

    def _add_ignore_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``ignore`` command parser."""
        parser = subparsers.add_parser(
            "ignore",
            help=(
                "Manage the per-project ignore list of tasks "
                "(always treated as in-progress during fetch)."
            ),
        )
        parser.add_argument(
            "--project",
            "-p",
            type=str,
            default=None,
            help=(
                "Project name (as used in config). "
                "If omitted, interactive project selection is shown."
            ),
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--add",
            nargs="+",
            type=str,
            metavar="TASK",
            help="Add task(s) to the ignore list (ID or name).",
        )
        group.add_argument(
            "--remove",
            nargs="+",
            type=str,
            metavar="TASK",
            help="Remove task(s) from the ignore list (ID or name).",
        )
        group.add_argument(
            "--list",
            action="store_true",
            default=False,
            dest="list_all",
            help=(
                "List ignored tasks for all projects. "
                "Does not require a CVAT connection."
            ),
        )
        parser.add_argument(
            "--description",
            "-d",
            type=str,
            default=None,
            help="Description / reason for ignoring (used with --add).",
        )
        parser.add_argument(
            "--silent",
            action="store_true",
            default=False,
            help="Suppress per-task warning during fetch (used with --add).",
        )

    def _add_labels_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``labels`` command parser."""
        parser = subparsers.add_parser(
            "labels",
            help=(
                "List and interactively edit project labels. "
                "Includes safety checks before label deletion."
            ),
        )
        parser.add_argument(
            "--project",
            "-p",
            type=str,
            default=None,
            help=(
                "Project ID or name. If omitted, "
                "interactive project selection is shown."
            ),
        )
        parser.add_argument(
            "--list",
            action="store_true",
            default=False,
            dest="list_labels",
            help="List project labels and exit.",
        )

    def _add_doctor_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``doctor`` command parser."""
        subparsers.add_parser(
            "doctor",
            help="Check configuration and image cache health.",
        )

    def _run_command(self, args: argparse.Namespace) -> None:
        """Dispatch parsed args to the target command implementation."""
        if args.command in ("setup", "setup-cache"):
            setup_path = Path(args.config) if args.config else get_config_path()
            if args.command == "setup":
                run_setup(setup_path)
            else:
                run_setup_cache(
                    setup_path,
                    reset=getattr(args, "reset", False),
                    list_paths=getattr(args, "list_paths", False),
                )
            return

        dispatch: dict[str, Callable[[], None]] = {
            "fetch": lambda: run_fetch(args),
            "fetch-task": lambda: run_fetch_task(args),
            "s3-sync": lambda: run_s3_sync(args),
            "upload": lambda: run_upload(args),
            "merge": lambda: run_merge(args),
            "ignore": lambda: run_ignore(args),
            "labels": lambda: run_labels(args),
            "doctor": run_doctor,
        }
        handler = dispatch.get(args.command)
        if handler is None:
            sys.exit(f"Неизвестная команда: {args.command}")
        handler()

    def run(self, argv: list[str] | None = None) -> None:
        """Run the CLI with the given arguments."""
        args = self._parser.parse_args(argv)
        self._run_command(args)


def main(argv: list[str] | None = None) -> None:
    """Compatibility entry point for setuptools/CLI wrappers."""
    CliApp().run(argv)


if __name__ == "__main__":
    main()

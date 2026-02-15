"""CLI entry point for cveta2."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from cveta2.commands.doctor import run_doctor
from cveta2.commands.fetch import run_fetch
from cveta2.commands.merge import run_merge
from cveta2.commands.s3_sync import run_s3_sync
from cveta2.commands.setup import run_setup, run_setup_cache
from cveta2.commands.upload import run_upload
from cveta2.config import CONFIG_PATH


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
        self._add_setup_parser(subparsers)
        self._add_setup_cache_parser(subparsers)
        self._add_s3_sync_parser(subparsers)
        self._add_upload_parser(subparsers)
        self._add_merge_parser(subparsers)
        self._add_doctor_parser(subparsers)

        return parser

    def _add_fetch_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``fetch`` command parser."""
        parser = subparsers.add_parser(
            "fetch",
            help="Fetch project bbox annotations and deleted images.",
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
            " (dataset, obsolete, in_progress).",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Additionally save unprocessed full CSV as raw.csv.",
        )
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
                "Path to deleted.txt — images listed there "
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
            if args.config:
                setup_path = Path(args.config)
            else:
                path_env = os.environ.get("CVETA2_CONFIG")
                setup_path = Path(path_env) if path_env else CONFIG_PATH
            if args.command == "setup":
                run_setup(setup_path)
            else:
                run_setup_cache(setup_path)
            return
        if args.command == "fetch":
            run_fetch(args)
            return
        if args.command == "s3-sync":
            run_s3_sync(args)
            return
        if args.command == "upload":
            run_upload(args)
            return
        if args.command == "merge":
            run_merge(args)
            return
        if args.command == "doctor":
            run_doctor()
            return
        sys.exit(f"Неизвестная команда: {args.command}")

    def run(self, argv: list[str] | None = None) -> None:
        """Run the CLI with the given arguments."""
        args = self._parser.parse_args(argv)
        self._run_command(args)


def main(argv: list[str] | None = None) -> None:
    """Compatibility entry point for setuptools/CLI wrappers."""
    CliApp().run(argv)


if __name__ == "__main__":
    main()

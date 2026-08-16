"""CLI entry point for cveta2."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cveta2.commands.convert import run_convert
from cveta2.commands.doctor import run_doctor
from cveta2.commands.fetch import run_fetch, run_fetch_task
from cveta2.commands.ignore import run_ignore
from cveta2.commands.labels import run_labels
from cveta2.commands.merge import run_merge
from cveta2.commands.s3_sync import run_s3_sync
from cveta2.commands.setup import run_setup, run_setup_cache
from cveta2.commands.setup_clearml import run_setup_clearml
from cveta2.commands.task_ops import (
    STATE_CLI_TO_CVAT,
    run_task_delete,
    run_task_drop_label,
    run_task_mark_deleted,
    run_task_status,
)
from cveta2.commands.upload import run_upload
from cveta2.commands.whats_new import run_whats_new
from cveta2.exceptions import Cveta2Error
from cveta2.models import JOB_STAGES

if TYPE_CHECKING:
    from collections.abc import Callable

_PROJECT_HELP = (
    "Project ID or name, optionally prefixed with an organization: "
    "ORG/PROJECT (default org comes from config; /PROJECT selects the "
    "personal workspace). If omitted, interactive project selection is shown."
)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One CLI subcommand: name, help, argument wiring and handler."""

    name: str
    help: str
    handler: Callable[[argparse.Namespace], None] | None = None
    configure: Callable[[argparse.ArgumentParser], None] | None = None
    subcommands: tuple[CommandSpec, ...] = ()


def _add_project_arg(
    parser: argparse.ArgumentParser,
    help_text: str = _PROJECT_HELP,
) -> None:
    parser.add_argument("--project", "-p", type=str, default=None, help=help_text)


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to YAML config (default: ~/.config/cveta2/config.yaml "
            "or CVETA2_CONFIG)."
        ),
    )


def _add_list_arg(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument("--list", dest="list_only", action="store_true", help=help_text)


def _add_task_common_args(parser: argparse.ArgumentParser) -> None:
    """Add ``--project`` / ``--task`` arguments shared by task actions."""
    _add_project_arg(parser)
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        required=True,
        help="Task ID or name.",
    )


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
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help=("Disable the task annotation cache entirely (no reads, no writes)."),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-download annotations from CVAT even for cached tasks "
            "and refresh the cache."
        ),
    )


def _configure_fetch(parser: argparse.ArgumentParser) -> None:
    _add_project_arg(parser)
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
        help="Save all records (including deletions) as raw.csv without partitioning.",
    )
    parser.add_argument(
        "--no-clearml",
        action="store_true",
        help="Skip publishing the fetched dataset to ClearML.",
    )
    _add_common_fetch_args(parser)


def _configure_fetch_task(parser: argparse.ArgumentParser) -> None:
    _add_project_arg(
        parser,
        help_text=(
            "Project ID or name (see fetch --help for the ORG/PROJECT form). "
            "If omitted, the project is inferred from the first numeric task "
            "ID; otherwise interactive selection is shown."
        ),
    )
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        nargs="*",
        default=None,
        metavar="TASK",
        help=(
            "Task ID(s) or name(s) to fetch: -t 42 43. "
            "If passed without values (-t), interactive "
            "multi-select is shown."
        ),
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="Directory to save dataset.csv and deleted.csv.",
    )
    _add_common_fetch_args(parser)


def _configure_setup_cache(parser: argparse.ArgumentParser) -> None:
    _add_config_arg(parser)
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Re-ask path for every project using cache_root/project_name "
            "as default (ignore existing paths)."
        ),
    )
    _add_list_arg(parser, "List current image cache paths and exit.")


def _configure_s3_sync(parser: argparse.ArgumentParser) -> None:
    _add_project_arg(
        parser,
        help_text=(
            "Sync only this project (name from image_cache config). "
            "If omitted, syncs every configured project."
        ),
    )
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help=(
            "One-run override of the S3 sync root "
            "(s3://bucket/prefix or a bare prefix). "
            "Takes priority over the sync_roots config section. "
            "Requires --project."
        ),
    )


def _configure_upload(parser: argparse.ArgumentParser) -> None:
    _add_project_arg(parser)
    parser.add_argument(
        "--dataset",
        "-d",
        required=True,
        help="Path to dataset.csv produced by the fetch command.",
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        type=str,
        default=None,
        metavar="LABEL",
        help=(
            "Instance labels selecting frames to upload "
            "(use __no_annotation__ for frames without annotations; "
            "'--labels all' selects every label). "
            "If omitted, interactive selection is shown."
        ),
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
    parser.add_argument(
        "--mark-all-deleted",
        action="store_true",
        help="Mark every uploaded image as deleted after task creation.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Continue the last unfinished upload of this dataset instead of "
            "creating a second task. Pass the same --dataset and --labels."
        ),
    )


def _configure_merge(parser: argparse.ArgumentParser) -> None:
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


def _configure_ignore(parser: argparse.ArgumentParser) -> None:
    _add_project_arg(
        parser,
        help_text=(
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
        dest="list_only",
        help=(
            "List ignored tasks for all projects. Does not require a CVAT connection."
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


def _configure_labels(parser: argparse.ArgumentParser) -> None:
    _add_project_arg(parser)
    _add_list_arg(parser, "List project labels and exit.")


def _configure_convert(parser: argparse.ArgumentParser) -> None:
    direction = parser.add_mutually_exclusive_group(required=True)
    direction.add_argument(
        "--to-yolo",
        action="store_true",
        default=False,
        help="Convert cveta2 CSV to YOLO detection format.",
    )
    direction.add_argument(
        "--from-yolo",
        action="store_true",
        default=False,
        help="Convert YOLO detection format to cveta2 CSV.",
    )
    direction.add_argument(
        "--to-coco",
        action="store_true",
        default=False,
        help="Convert cveta2 CSV to COCO detection format (rfdetr-compatible).",
    )
    parser.add_argument(
        "--dataset",
        "-d",
        type=str,
        default=None,
        help="Path to dataset.csv (for --to-yolo / --to-coco).",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=None,
        help="Path to YOLO dataset directory (for --from-yolo).",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help=("Output path: directory for --to-yolo, CSV file for --from-yolo."),
    )
    parser.add_argument(
        "--link-mode",
        choices=["reflink", "hardlink", "symlink", "copy", "auto"],
        default="auto",
        help=(
            "How to place images in YOLO output "
            "(default: auto — reflink with copy fallback)."
        ),
    )
    parser.add_argument(
        "--image-dir",
        nargs="+",
        type=str,
        default=None,
        metavar="DIR",
        help=("Additional directories to search for images: --image-dir d1 d2."),
    )
    parser.add_argument(
        "--names-file",
        type=str,
        default=None,
        help=(
            "YAML file with class names for --from-yolo "
            "prediction mode (format: {0: name, ...} or "
            "{names: {0: name, ...}})."
        ),
    )
    parser.add_argument(
        "--read-all-sizes",
        action="store_true",
        default=False,
        help=(
            "Read dimensions from every image individually "
            "(for --from-yolo). By default, reads only the "
            "first image and assumes all have the same size."
        ),
    )


def _configure_task_mark_deleted(parser: argparse.ArgumentParser) -> None:
    _add_task_common_args(parser)
    parser.add_argument(
        "--frame",
        nargs="+",
        type=int,
        default=None,
        metavar="N",
        help="Frame ID(s) to mark as deleted: --frame 1 2.",
    )
    parser.add_argument(
        "--image",
        nargs="+",
        type=str,
        default=None,
        metavar="NAME",
        help="Image name(s) to mark as deleted: --image a.jpg b.jpg.",
    )


def _configure_task_drop_label(parser: argparse.ArgumentParser) -> None:
    _add_task_common_args(parser)
    parser.add_argument(
        "--label",
        required=True,
        help="Label name whose annotations will be deleted.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )


def _configure_task_delete(parser: argparse.ArgumentParser) -> None:
    _add_task_common_args(parser)
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )


def _configure_task_status(parser: argparse.ArgumentParser) -> None:
    _add_task_common_args(parser)
    parser.add_argument(
        "--stage",
        choices=JOB_STAGES,
        default=None,
        help="Job stage to set on every job of the task.",
    )
    parser.add_argument(
        "--state",
        choices=sorted(STATE_CLI_TO_CVAT),
        default=None,
        help="Job state to set on every job of the task.",
    )


def _configure_setup_clearml(parser: argparse.ArgumentParser) -> None:
    _add_config_arg(parser)
    _add_list_arg(parser, "List current ClearML project mappings and exit.")


def _configure_doctor(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cache",
        action="store_true",
        help=(
            "Fix cache permissions: grant the group rwx on every cache path "
            "owned by the current user, and list the users who must run this "
            "themselves for the rest."
        ),
    )


def _configure_whats_new(parser: argparse.ArgumentParser) -> None:
    _add_project_arg(parser)
    parser.add_argument(
        "--dataset",
        "-d",
        required=True,
        help="Path to dataset.csv produced by the fetch command.",
    )


def _command_specs() -> tuple[CommandSpec, ...]:
    """Build the command registry.

    Built at call time (inside ``CliApp.__init__``) so that tests
    patching ``cveta2.cli.run_*`` see their mocks captured.
    """
    return (
        CommandSpec(
            "fetch",
            "Fetch all project bbox annotations and deleted images.",
            run_fetch,
            _configure_fetch,
        ),
        CommandSpec(
            "fetch-task",
            "Fetch bbox annotations for specific task(s) in a project.",
            run_fetch_task,
            _configure_fetch_task,
        ),
        CommandSpec(
            "setup",
            "Interactively configure CVAT connection settings.",
            run_setup,
            _add_config_arg,
        ),
        CommandSpec(
            "setup-cache",
            "Interactively configure image cache directories for all projects.",
            run_setup_cache,
            _configure_setup_cache,
        ),
        CommandSpec(
            "s3-sync",
            "Sync images from S3 cloud storage to local cache "
            "for all configured projects.",
            run_s3_sync,
            _configure_s3_sync,
        ),
        CommandSpec(
            "upload",
            "Create a CVAT task from dataset.csv: filter classes, "
            "upload images to S3, create task with cloud storage.",
            run_upload,
            _configure_upload,
        ),
        CommandSpec(
            "merge",
            "Merge two dataset CSV files. For images in both, new annotations win.",
            run_merge,
            _configure_merge,
        ),
        CommandSpec(
            "ignore",
            "Manage the per-project ignore list of tasks "
            "(always treated as in-progress during fetch).",
            run_ignore,
            _configure_ignore,
        ),
        CommandSpec(
            "labels",
            "List and interactively edit project labels. "
            "Includes safety checks before label deletion.",
            run_labels,
            _configure_labels,
        ),
        CommandSpec(
            "convert",
            "Convert between cveta2 CSV and YOLO/COCO detection formats.",
            run_convert,
            _configure_convert,
        ),
        CommandSpec(
            "task",
            "Task write operations: mark-deleted, drop-label, delete, status.",
            subcommands=(
                CommandSpec(
                    "mark-deleted",
                    "Mark task frames as deleted by frame ID and/or image name.",
                    run_task_mark_deleted,
                    _configure_task_mark_deleted,
                ),
                CommandSpec(
                    "drop-label",
                    "Delete all annotations with the given label from a task.",
                    run_task_drop_label,
                    _configure_task_drop_label,
                ),
                CommandSpec(
                    "delete",
                    "Delete a task permanently.",
                    run_task_delete,
                    _configure_task_delete,
                ),
                CommandSpec(
                    "status",
                    "Set stage and/or state for all jobs of a task.",
                    run_task_status,
                    _configure_task_status,
                ),
            ),
        ),
        CommandSpec(
            "doctor",
            "Check configuration and cache health.",
            run_doctor,
            _configure_doctor,
        ),
        CommandSpec(
            "setup-clearml",
            "Interactively configure ClearML project mappings for dataset publishing.",
            run_setup_clearml,
            _configure_setup_clearml,
        ),
        CommandSpec(
            "whats-new",
            "List tasks completed after the tasks in a fetched dataset CSV.",
            run_whats_new,
            _configure_whats_new,
        ),
    )


def _register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    spec: CommandSpec,
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

    def run(self, argv: list[str] | None = None) -> None:
        """Run the CLI with the given arguments."""
        args = self._parser.parse_args(argv)
        self._run_command(args)


def main(argv: list[str] | None = None) -> None:
    """Compatibility entry point for setuptools/CLI wrappers."""
    CliApp().run(argv)


if __name__ == "__main__":
    main()

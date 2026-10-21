"""CLI adapter for the ``cveta2 merge`` command.

Only argument mapping lives here; the merge logic itself is
:mod:`cveta2.application.use_cases.merge`.
"""

from typing import TYPE_CHECKING

from cveta2.composition.conversion import merge_datasets

if TYPE_CHECKING:
    import argparse


def configure_merge(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``merge`` command arguments."""
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
        "--by-task",
        action="store_true",
        help=(
            "Resolve conflicts by task_id instead "
            "of argument order (requires task_id column)."
        ),
    )


def run_merge(args: "argparse.Namespace") -> None:
    """Run the ``merge`` command."""
    merge_datasets(
        args.old,
        args.new,
        args.output,
        deleted=args.deleted,
        by_task=args.by_task,
    )

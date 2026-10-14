"""CLI adapter for the ``cveta2 merge`` command.

Only argument mapping lives here; the merge logic itself is
:mod:`cveta2.application.use_cases.merge`.
"""

from typing import TYPE_CHECKING

from cveta2.composition.conversion import merge_datasets

if TYPE_CHECKING:
    import argparse


def run_merge(args: "argparse.Namespace") -> None:
    """Run the ``merge`` command."""
    merge_datasets(
        args.old,
        args.new,
        args.output,
        deleted=args.deleted,
        by_task=args.by_task,
    )

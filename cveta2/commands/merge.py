"""CLI adapter for the ``cveta2 merge`` command.

Only argument mapping and ``sys.exit`` UX live here; the merge logic itself
is :mod:`cveta2.services.merge`.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from cveta2.exceptions import Cveta2Error
from cveta2.services.merge import merge_datasets

if TYPE_CHECKING:
    import argparse


def run_merge(args: argparse.Namespace) -> None:
    """Run the ``merge`` command."""
    try:
        merge_datasets(
            args.old,
            args.new,
            args.output,
            deleted=args.deleted,
            by_time=args.by_time,
        )
    except Cveta2Error as e:
        sys.exit(str(e))

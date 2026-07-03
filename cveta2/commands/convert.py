"""CLI adapter for the ``cveta2 convert`` command.

Only argument mapping and ``sys.exit`` UX live here; the conversion logic
itself is :mod:`cveta2.services.convert`.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from cveta2.exceptions import Cveta2Error
from cveta2.services.convert import (
    convert_from_yolo,
    convert_to_coco,
    convert_to_yolo,
)

if TYPE_CHECKING:
    import argparse


def run_convert(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate conversion direction."""
    try:
        _dispatch(args)
    except Cveta2Error as e:
        sys.exit(str(e))


def _dispatch(args: argparse.Namespace) -> None:
    """Map CLI arguments onto the conversion service functions."""
    if getattr(args, "to_yolo", False):
        convert_to_yolo(
            args.dataset,
            args.output,
            image_dirs=getattr(args, "image_dir", None),
            link_mode=args.link_mode or "auto",
        )
    elif getattr(args, "from_yolo", False):
        convert_from_yolo(
            args.input,
            args.output,
            names_file=args.names_file,
            read_all_sizes=getattr(args, "read_all_sizes", False),
            image_dirs=getattr(args, "image_dir", None),
        )
    elif getattr(args, "to_coco", False):
        convert_to_coco(
            args.dataset,
            args.output,
            image_dirs=getattr(args, "image_dir", None),
            link_mode=args.link_mode or "auto",
        )
    else:
        raise Cveta2Error("Ошибка: укажите --to-yolo, --from-yolo или --to-coco")

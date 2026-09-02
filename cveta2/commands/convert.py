"""CLI adapter for the ``cveta2 convert`` command.

Only argument mapping lives here; the conversion logic itself is
:mod:`cveta2.services.convert`.
"""

from __future__ import annotations

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
    """Map CLI arguments onto the conversion service functions."""
    if (args.to_yolo or args.to_coco) and not args.dataset:
        raise Cveta2Error("Ошибка: для --to-yolo / --to-coco укажите --dataset / -d.")
    if args.from_yolo and not args.input:
        raise Cveta2Error("Ошибка: для --from-yolo укажите --input / -i.")
    if args.to_yolo:
        convert_to_yolo(
            args.dataset,
            args.output,
            image_dirs=args.image_dir,
            link_mode=args.link_mode,
        )
    elif args.from_yolo:
        convert_from_yolo(
            args.input,
            args.output,
            names_file=args.names_file,
            read_all_sizes=args.read_all_sizes,
            image_dirs=args.image_dir,
        )
    elif args.to_coco:
        convert_to_coco(
            args.dataset,
            args.output,
            image_dirs=args.image_dir,
            link_mode=args.link_mode,
        )
    else:
        raise Cveta2Error("Ошибка: укажите --to-yolo, --from-yolo или --to-coco")

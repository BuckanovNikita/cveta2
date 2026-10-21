"""CLI adapter for the ``cveta2 convert`` command.

Only argument mapping lives here; the conversion logic itself is
:mod:`cveta2.application.use_cases.convert`.
"""

from typing import TYPE_CHECKING

from cveta2.composition.conversion import (
    convert_from_yolo,
    convert_to_coco,
    convert_to_yolo,
)
from cveta2.domain.errors import Cveta2Error

if TYPE_CHECKING:
    import argparse


def configure_convert(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``convert`` command arguments."""
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


def run_convert(args: "argparse.Namespace") -> None:
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
    else:
        convert_to_coco(
            args.dataset,
            args.output,
            image_dirs=args.image_dir,
            link_mode=args.link_mode,
        )

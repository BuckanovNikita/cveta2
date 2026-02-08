"""CLI entry point for cveta2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from cveta2.client import fetch_annotations
from cveta2.config import CvatConfig


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add connection / auth arguments shared by all sub-commands."""
    parser.add_argument(
        "--host",
        default="",
        help="CVAT server URL (or set CVAT_HOST env var, or config file).",
    )
    parser.add_argument(
        "--project-id",
        type=int,
        required=True,
        help="ID of the CVAT project.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Personal Access Token (or set CVAT_TOKEN env var, or config file).",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="CVAT username (or set CVAT_USERNAME env var, or config file).",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="CVAT password (or set CVAT_PASSWORD env var, or config file).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to TOML config file (default: ~/.config/cveta2/config.toml).",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CVAT project utilities.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- fetch ----------------------------------------------------------------
    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Fetch project bbox annotations and deleted images.",
    )
    _add_common_args(fetch_parser)
    fetch_parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output JSON file path. Prints to stdout if omitted.",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Main CLI entry point."""
    args = _parse_args(argv)

    config_path = Path(args.config) if args.config else None
    load_kwargs: dict[str, object] = {
        "cli_host": args.host,
        "cli_token": args.token,
        "cli_username": args.username,
        "cli_password": args.password,
    }
    if config_path is not None:
        load_kwargs["config_path"] = config_path

    cfg = CvatConfig.load(**load_kwargs)  # type: ignore[arg-type]

    if not cfg.host:
        sys.exit(
            "Error: CVAT host is required. "
            "Provide --host, set CVAT_HOST, or add it to ~/.config/cveta2/config.toml."
        )

    if args.command == "fetch":
        result = fetch_annotations(cfg, project_id=args.project_id)
        json_output = result.model_dump_json(indent=2)
        if args.output:
            Path(args.output).write_text(json_output)
            logger.info(f"Output saved to {args.output}")
        else:
            sys.stdout.write(json_output + "\n")


if __name__ == "__main__":
    main()

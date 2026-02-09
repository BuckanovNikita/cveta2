"""CLI entry point for cveta2."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

import pandas as pd

from loguru import logger

from cveta2.client import fetch_annotations
from cveta2.config import CONFIG_PATH, CvatConfig
from cveta2.models import BBoxAnnotation


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
    fetch_parser.add_argument(
        "--annotations-csv",
        default=None,
        help="Path to save all annotations as CSV.",
    )
    fetch_parser.add_argument(
        "--deleted-txt",
        default=None,
        help="Path to save deleted image names (one per line).",
    )
    fetch_parser.add_argument(
        "--completed-only",
        action="store_true",
        help="Process only tasks with status 'completed'.",
    )

    # --- setup ---------------------------------------------------------------
    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactively configure CVAT connection settings.",
    )
    setup_parser.add_argument(
        "--config",
        default=None,
        help="Path to TOML config file (default: ~/.config/cveta2/config.toml).",
    )

    return parser.parse_args(argv)


def _annotation_to_csv_row(a: BBoxAnnotation) -> dict[str, str | int | float | bool]:
    """Convert BBoxAnnotation to a flat dict for CSV (attributes as JSON string)."""
    row = a.model_dump()
    attrs = row.pop("attributes")
    row["attributes"] = json.dumps(attrs, ensure_ascii=False)
    return row


def _write_annotations_csv(annotations: list[BBoxAnnotation], path: Path) -> None:
    """Write all annotations to a CSV file using pandas."""
    df = pd.DataFrame([_annotation_to_csv_row(a) for a in annotations])
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info(f"Annotations CSV saved to {path} ({len(annotations)} rows)")


def _write_deleted_txt(deleted_image_names: list[str], path: Path) -> None:
    """Write deleted image names to a text file, one per line."""
    path.write_text("\n".join(deleted_image_names) + ("\n" if deleted_image_names else ""), encoding="utf-8")
    logger.info(f"Deleted images list saved to {path} ({len(deleted_image_names)} names)")


def _run_setup(config_path: Path) -> None:
    """Interactively ask user for CVAT settings and save them to config file."""
    existing = CvatConfig.from_file(config_path)

    host_default = existing.host or "https://app.cvat.ai"
    host = input(f"CVAT host [{host_default}]: ").strip() or host_default

    logger.info("Аутентификация: токен (t) или логин/пароль (p)?")
    auth_choice = ""
    while auth_choice not in ("t", "p"):
        auth_choice = input("Выберите [t/p]: ").strip().lower()

    token: str | None = None
    username: str | None = None
    password: str | None = None

    if auth_choice == "t":
        token_default = existing.token or ""
        prompt = "Personal Access Token"
        if token_default:
            prompt += f" [{token_default[:6]}...]"
        prompt += ": "
        token = input(prompt).strip() or token_default
        if not token:
            logger.warning("Токен не указан — его можно добавить позже.")
    else:
        username_default = existing.username or ""
        prompt = "Имя пользователя"
        if username_default:
            prompt += f" [{username_default}]"
        prompt += ": "
        username = input(prompt).strip() or username_default
        password = getpass.getpass("Пароль: ")
        if not password and existing.password:
            password = existing.password
            logger.info("Пароль не изменён (использован существующий).")

    cfg = CvatConfig(
        host=host,
        token=token,
        username=username,
        password=password,
    )
    saved_path = cfg.save_to_file(config_path)
    logger.info(f"Готово! Конфигурация сохранена в {saved_path}")


def main(argv: list[str] | None = None) -> None:
    """Run the CLI with the given arguments."""
    args = _parse_args(argv)

    if args.command == "setup":
        setup_path = Path(args.config) if args.config else CONFIG_PATH
        _run_setup(setup_path)
        return

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
        result = fetch_annotations(
            cfg,
            project_id=args.project_id,
            completed_only=args.completed_only,
        )
        json_output = result.model_dump_json(indent=2)
        if args.output:
            Path(args.output).write_text(json_output)
            logger.info(f"Output saved to {args.output}")
        else:
            sys.stdout.write(json_output + "\n")
        if args.annotations_csv:
            _write_annotations_csv(result.annotations, Path(args.annotations_csv))
        if args.deleted_txt:
            _write_deleted_txt(
                [d.image_name for d in result.deleted_images],
                Path(args.deleted_txt),
            )


if __name__ == "__main__":
    main()

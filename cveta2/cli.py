"""CLI entry point for cveta2."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2.client import CvatClient
from cveta2.config import CONFIG_PATH, CvatConfig

if TYPE_CHECKING:
    from cveta2.models import BBoxAnnotation


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
        self._add_common_args(parser)
        parser.add_argument(
            "--output",
            "-o",
            default=None,
            help="Output JSON file path. Prints to stdout if omitted.",
        )
        parser.add_argument(
            "--annotations-csv",
            default=None,
            help="Path to save all annotations as CSV.",
        )
        parser.add_argument(
            "--deleted-txt",
            default=None,
            help="Path to save deleted image names (one per line).",
        )
        parser.add_argument(
            "--completed-only",
            action="store_true",
            help="Process only tasks with status 'completed'.",
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
            help="Path to YAML config file (default: ~/.config/cveta2/config.yaml).",
        )

    def _add_common_args(self, parser: argparse.ArgumentParser) -> None:
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
            help="Path to YAML config file (default: ~/.config/cveta2/config.yaml).",
        )

    def _write_annotations_csv(
        self,
        annotations: list[BBoxAnnotation],
        path: Path,
    ) -> None:
        """Write all annotations to a CSV file using pandas."""
        df = pd.DataFrame([a.to_csv_row() for a in annotations])
        df.to_csv(path, index=False, encoding="utf-8")
        logger.info(f"Annotations CSV saved to {path} ({len(annotations)} rows)")

    def _write_deleted_txt(self, deleted_image_names: list[str], path: Path) -> None:
        """Write deleted image names to a text file, one per line."""
        content = "\n".join(deleted_image_names)
        if deleted_image_names:
            content += "\n"
        path.write_text(content, encoding="utf-8")
        logger.info(
            f"Deleted images list saved to {path} ({len(deleted_image_names)} names)"
        )

    def _run_setup(self, config_path: Path) -> None:
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

    def _load_config(self, args: argparse.Namespace) -> CvatConfig:
        if args.config:
            return CvatConfig.load(
                cli_host=args.host,
                cli_token=args.token,
                cli_username=args.username,
                cli_password=args.password,
                config_path=Path(args.config),
            )
        return CvatConfig.load(
            cli_host=args.host,
            cli_token=args.token,
            cli_username=args.username,
            cli_password=args.password,
        )

    def _require_host(self, cfg: CvatConfig) -> None:
        """Abort with a friendly message when host is not configured."""
        if cfg.host:
            return
        sys.exit(
            "Error: CVAT host is required. "
            "Provide --host, set CVAT_HOST, or add it to ~/.config/cveta2/config.yaml."
        )

    def _write_json_output(self, content: str, output_path: str | None) -> None:
        """Write command JSON output to file or stdout."""
        if output_path:
            Path(output_path).write_text(content, encoding="utf-8")
            logger.info(f"Output saved to {output_path}")
            return
        sys.stdout.write(content + "\n")

    def _run_fetch(self, args: argparse.Namespace) -> None:
        """Run the ``fetch`` command."""
        cfg = self._load_config(args)
        self._require_host(cfg)

        client = CvatClient(cfg)
        result = client.fetch_annotations(
            project_id=args.project_id,
            completed_only=args.completed_only,
        )
        self._write_json_output(result.model_dump_json(indent=2), args.output)

        if args.annotations_csv:
            self._write_annotations_csv(
                result.annotations,
                Path(args.annotations_csv),
            )
        if args.deleted_txt:
            self._write_deleted_txt(
                [d.image_name for d in result.deleted_images],
                Path(args.deleted_txt),
            )

    def _run_command(self, args: argparse.Namespace) -> None:
        """Dispatch parsed args to the target command implementation."""
        if args.command == "setup":
            setup_path = Path(args.config) if args.config else CONFIG_PATH
            self._run_setup(setup_path)
            return
        if args.command == "fetch":
            self._run_fetch(args)
            return
        sys.exit(f"Unknown command: {args.command}")

    def run(self, argv: list[str] | None = None) -> None:
        """Run the CLI with the given arguments."""
        args = self._parser.parse_args(argv)
        self._run_command(args)


def main(argv: list[str] | None = None) -> None:
    """Compatibility entry point for setuptools/CLI wrappers."""
    CliApp().run(argv)


if __name__ == "__main__":
    main()

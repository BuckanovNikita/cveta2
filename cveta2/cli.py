"""CLI entry point for cveta2."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import pandas as pd
import questionary
from loguru import logger

from cveta2.client import CvatClient, _project_annotations_to_csv_rows
from cveta2.config import (
    CONFIG_PATH,
    CvatConfig,
    is_interactive_disabled,
    require_interactive,
)
from cveta2.dataset_partition import PartitionResult, partition_annotations_df
from cveta2.projects_cache import ProjectInfo, load_projects_cache, save_projects_cache

_RESCAN_VALUE = "__rescan__"


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
        parser.add_argument(
            "--project",
            "-p",
            type=str,
            default=None,
            help=(
                "Project ID or name. If omitted, "
                "interactive project selection is shown."
            ),
        )
        parser.add_argument(
            "--output-dir",
            "-o",
            required=True,
            help="Directory to save partitioned CSV files (dataset, obsolete, in_progress).",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Additionally save unprocessed full CSV as raw.csv.",
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
            help=(
                "Path to YAML config (default: ~/.config/cveta2/config.yaml "
                "or CVETA2_CONFIG)."
            ),
        )

    @staticmethod
    def _write_df_csv(df: pd.DataFrame, path: Path, label: str) -> None:
        """Write a DataFrame to CSV and log the result."""
        df.to_csv(path, index=False, encoding="utf-8")
        logger.info(f"{label} saved to {path} ({len(df)} rows)")

    @staticmethod
    def _write_deleted_txt(deleted_names: list[str], path: Path) -> None:
        """Write deleted image names to a text file, one per line."""
        content = "\n".join(deleted_names)
        if deleted_names:
            content += "\n"
        path.write_text(content, encoding="utf-8")
        logger.info(f"Deleted images list saved to {path} ({len(deleted_names)} names)")

    def _write_partition_result(
        self,
        partition: PartitionResult,
        output_dir: Path,
    ) -> None:
        """Write all partition DataFrames and deleted.txt into *output_dir*."""
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_df_csv(partition.dataset, output_dir / "dataset.csv", "Dataset CSV")
        self._write_df_csv(partition.obsolete, output_dir / "obsolete.csv", "Obsolete CSV")
        self._write_df_csv(
            partition.in_progress,
            output_dir / "in_progress.csv",
            "In-progress CSV",
        )
        self._write_deleted_txt(partition.deleted_names, output_dir / "deleted.txt")

    def _run_setup(self, config_path: Path) -> None:
        """Interactively ask user for CVAT settings and save them to config file."""
        require_interactive(
            "The 'setup' command is fully interactive. "
            "Configure via env vars (CVAT_HOST, CVAT_TOKEN, etc.) "
            "or edit the config file directly."
        )
        existing = CvatConfig.from_file(config_path)

        host_default = existing.host or "https://app.cvat.ai"
        host = input(f"CVAT host [{host_default}]: ").strip() or host_default
        org_default = existing.organization or ""
        org_prompt = "Organization slug (optional)"
        if org_default:
            org_prompt += f" [{org_default}]"
        org_prompt += ": "
        organization = input(org_prompt).strip() or org_default

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
            organization=organization or None,
            token=token,
            username=username,
            password=password,
        )
        saved_path = cfg.save_to_file(config_path)
        logger.info(f"Готово! Конфигурация сохранена в {saved_path}")

    def _load_config(self, config_path: Path | None = None) -> CvatConfig:
        """Load config from file and env. Path from CVETA2_CONFIG or argument."""
        if config_path is not None:
            return CvatConfig.load(config_path=config_path)
        path_env = os.environ.get("CVETA2_CONFIG")
        path = Path(path_env) if path_env else None
        return CvatConfig.load(config_path=path)

    def _require_host(self, cfg: CvatConfig) -> None:
        """Abort with a friendly message when host is not configured."""
        if cfg.host:
            return
        config_path = os.environ.get("CVETA2_CONFIG", str(CONFIG_PATH))
        sys.exit(
            "Error: CVAT host is not configured.\n"
            "Run setup to save credentials:\n  cveta2 setup\n"
            "Or set env: CVAT_HOST and (CVAT_TOKEN or CVAT_USERNAME/CVAT_PASSWORD).\n"
            f"Config file path: {config_path}"
        )

    def _build_project_choices(
        self,
        projects: list[ProjectInfo],
    ) -> list[questionary.Choice]:
        """Build questionary choices: project list + rescan option last."""
        choices: list[questionary.Choice] = [
            questionary.Choice(title=f"{p.name} (id={p.id})", value=p.id)
            for p in projects
        ]
        choices.append(
            questionary.Choice(
                title="↻ Обновить список проектов с CVAT",
                value=_RESCAN_VALUE,
            ),
        )
        return choices

    def _run_fetch_tui_select_project(self, cfg: CvatConfig) -> int:
        """Interactive project selection via TUI list.

        Arrow keys to pick, with an option to rescan CVAT.
        """
        require_interactive("Pass --project / -p to specify the project ID or name.")
        client = CvatClient(cfg)
        projects = load_projects_cache()
        while True:
            if not projects:
                logger.info("Кэш проектов пуст. Загружаю список с CVAT...")
                projects = client.list_projects()
                save_projects_cache(projects)
                if not projects:
                    sys.exit("Нет доступных проектов.")
            choices = self._build_project_choices(projects)
            answer = questionary.select(
                "Выберите проект:",
                choices=choices,
                use_shortcuts=False,
                use_indicator=True,
                use_search_filter=True,
                use_jk_keys=False,
            ).ask()
            if answer is None:
                sys.exit("Выбор отменён.")
            if answer == _RESCAN_VALUE:
                projects = client.list_projects()
                save_projects_cache(projects)
                logger.info(f"Загружено проектов: {len(projects)}")
                continue
            return int(answer)

    def _run_fetch(self, args: argparse.Namespace) -> None:
        """Run the ``fetch`` command."""
        cfg = self._load_config()
        self._require_host(cfg)

        client = CvatClient(cfg)
        if args.project is not None:
            cached = load_projects_cache()
            try:
                project_id = client.resolve_project_id(
                    args.project.strip(), cached=cached
                )
            except ValueError as e:
                sys.exit(str(e))
        else:
            project_id = self._run_fetch_tui_select_project(cfg)

        result = client.fetch_annotations(
            project_id=project_id,
            completed_only=args.completed_only,
        )

        output_dir = Path(args.output_dir)
        if output_dir.exists():
            if is_interactive_disabled():
                logger.info(
                    f"Output directory {output_dir} already exists "
                    f"— overwriting (non-interactive mode)."
                )
            else:
                answer = questionary.select(
                    f"Папка {output_dir} уже существует. Что делать?",
                    choices=[
                        questionary.Choice(title="Перезаписать", value="overwrite"),
                        questionary.Choice(title="Указать другой путь", value="change"),
                        questionary.Choice(title="Отмена", value="cancel"),
                    ],
                    use_shortcuts=False,
                    use_indicator=True,
                ).ask()
                if answer is None or answer == "cancel":
                    sys.exit("Отменено.")
                if answer == "change":
                    new_path = input("Новый путь: ").strip()
                    if not new_path:
                        sys.exit("Путь не указан.")
                    output_dir = Path(new_path)

        rows = _project_annotations_to_csv_rows(result)
        df = pd.DataFrame(rows)

        if args.raw:
            output_dir.mkdir(parents=True, exist_ok=True)
            self._write_df_csv(df, output_dir / "raw.csv", "Raw CSV")

        partition = partition_annotations_df(df, result.deleted_images)
        self._write_partition_result(partition, output_dir)

    def _run_command(self, args: argparse.Namespace) -> None:
        """Dispatch parsed args to the target command implementation."""
        if args.command == "setup":
            if args.config:
                setup_path = Path(args.config)
            else:
                path_env = os.environ.get("CVETA2_CONFIG")
                setup_path = Path(path_env) if path_env else CONFIG_PATH
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

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

from cveta2.client import CvatClient
from cveta2.config import (
    CONFIG_PATH,
    CvatConfig,
    ImageCacheConfig,
    is_interactive_disabled,
    load_image_cache_config,
    require_interactive,
    save_image_cache_config,
)
from cveta2.dataset_partition import PartitionResult, partition_annotations_df
from cveta2.exceptions import Cveta2Error
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
        self._add_s3_sync_parser(subparsers)

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
            help="Directory to save partitioned CSV files "
            " (dataset, obsolete, in_progress).",
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
        parser.add_argument(
            "--no-images",
            action="store_true",
            help="Skip downloading images from S3 cloud storage.",
        )
        parser.add_argument(
            "--images-dir",
            type=str,
            default=None,
            help=(
                "Override image cache directory for this run "
                "(takes precedence over config mapping)."
            ),
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

    def _add_s3_sync_parser(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        """Add the ``s3-sync`` command parser."""
        parser = subparsers.add_parser(
            "s3-sync",
            help=(
                "Sync images from S3 cloud storage to local cache "
                "for all configured projects."
            ),
        )
        parser.add_argument(
            "--project",
            "-p",
            type=str,
            default=None,
            help=(
                "Sync only this project (name from image_cache config). "
                "If omitted, syncs every configured project."
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

    def _resolve_output_dir(self, output_dir: Path) -> Path:
        """Resolve output directory, prompting on overwrite if interactive."""
        if not output_dir.exists():
            return output_dir
        if is_interactive_disabled():
            logger.info(
                f"Папка {output_dir} уже существует "
                f"— перезапись (неинтерактивный режим)."
            )
            return output_dir
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
            return Path(new_path)
        return output_dir

    def _write_partition_result(
        self,
        partition: PartitionResult,
        output_dir: Path,
    ) -> None:
        """Write all partition DataFrames and deleted.txt into *output_dir*."""
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_df_csv(partition.dataset, output_dir / "dataset.csv", "Dataset CSV")
        self._write_df_csv(
            partition.obsolete, output_dir / "obsolete.csv", "Obsolete CSV"
        )
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
        host = input(f"Хост CVAT [{host_default}]: ").strip() or host_default
        org_default = existing.organization or ""
        org_prompt = "Slug организации (необязательно)"
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
            prompt = "Персональный токен доступа"
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

        image_cache = self._setup_image_cache(config_path)
        saved_path = cfg.save_to_file(config_path, image_cache=image_cache)
        logger.info(f"Готово! Конфигурация сохранена в {saved_path}")

    @staticmethod
    def _setup_image_cache(config_path: Path) -> ImageCacheConfig:
        """Interactively configure per-project image cache directories."""
        image_cache = load_image_cache_config(config_path)
        setup_images = (
            input("Настроить пути для кэширования изображений? [y/n]: ").strip().lower()
        )
        if setup_images != "y":
            return image_cache
        while True:
            proj_name = input("Имя проекта (пустая строка — завершить): ").strip()
            if not proj_name:
                break
            proj_path = input(f"Путь для изображений проекта {proj_name!r}: ").strip()
            if proj_path:
                resolved = Path(proj_path).resolve()
                image_cache.set_cache_dir(proj_name, resolved)
                logger.info(f"  {proj_name} -> {resolved}")
        return image_cache

    def _load_config(self, config_path: Path | None = None) -> CvatConfig:
        """Load config from file and env. Path from CVETA2_CONFIG or argument."""
        return CvatConfig.load(config_path=config_path)

    def _require_host(self, cfg: CvatConfig) -> None:
        """Abort with a friendly message when host is not configured."""
        if cfg.host:
            return
        config_path = os.environ.get("CVETA2_CONFIG", str(CONFIG_PATH))
        sys.exit(
            "Ошибка: хост CVAT не настроен.\n"
            "Запустите setup для сохранения настроек:\n  cveta2 setup\n"
            "Или задайте переменные окружения: CVAT_HOST и "
            "(CVAT_TOKEN или CVAT_USERNAME/CVAT_PASSWORD).\n"
            f"Файл конфигурации: {config_path}"
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

    def _run_fetch_tui_select_project(self, client: CvatClient) -> int:
        """Interactive project selection via TUI list.

        Arrow keys to pick, with an option to rescan CVAT.
        """
        require_interactive("Pass --project / -p to specify the project ID or name.")
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

    def _resolve_images_dir(
        self,
        args: argparse.Namespace,
        project_name: str,
    ) -> Path | None:
        """Resolve image cache directory for the given project.

        Returns None if ``--no-images`` or download should be skipped.
        """
        if args.no_images:
            return None

        # --images-dir takes top priority
        if args.images_dir:
            return Path(args.images_dir).resolve()

        # Look up per-project mapping in config
        ic_cfg = load_image_cache_config()
        cached_dir = ic_cfg.get_cache_dir(project_name)
        if cached_dir is not None:
            return cached_dir

        # Not configured — interactive prompt or error
        if is_interactive_disabled():
            sys.exit(
                f"Ошибка: путь кэширования изображений для проекта "
                f"{project_name!r} не настроен.\n"
                f"Укажите --images-dir, --no-images или добавьте "
                f"image_cache.{project_name} в конфигурацию."
            )

        path_str = input(
            f"Укажите путь для кэширования изображений проекта {project_name!r}: "
        ).strip()
        if not path_str:
            logger.warning("Путь не указан — загрузка изображений пропущена.")
            return None

        new_path = Path(path_str).resolve()
        ic_cfg.set_cache_dir(project_name, new_path)
        save_image_cache_config(ic_cfg)
        return new_path

    def _run_fetch(self, args: argparse.Namespace) -> None:
        """Run the ``fetch`` command."""
        cfg = self._load_config()
        self._require_host(cfg)

        project_name: str | None = None

        with CvatClient(cfg) as client:
            if args.project is not None:
                cached = load_projects_cache()
                try:
                    project_id = client.resolve_project_id(
                        args.project.strip(), cached=cached
                    )
                except Cveta2Error as e:
                    sys.exit(str(e))
                project_name = args.project.strip()
            else:
                project_id = self._run_fetch_tui_select_project(client)

            # Try to resolve human-readable project name from cache
            if project_name is None or project_name.isdigit():
                for p in load_projects_cache():
                    if p.id == project_id:
                        project_name = p.name
                        break

            if project_name is None:
                project_name = str(project_id)

            result = client.fetch_annotations(
                project_id=project_id,
                completed_only=args.completed_only,
            )

            # Image download (within the CvatClient context)
            images_dir = self._resolve_images_dir(args, project_name)
            if images_dir is not None:
                stats = client.download_images(result, images_dir)
                logger.info(
                    f"Изображения: {stats.downloaded} загружено, "
                    f"{stats.cached} из кэша, {stats.failed} ошибок"
                )

        output_dir = self._resolve_output_dir(Path(args.output_dir))

        rows = result.to_csv_rows()
        df = pd.DataFrame(rows)

        if args.raw:
            output_dir.mkdir(parents=True, exist_ok=True)
            self._write_df_csv(df, output_dir / "raw.csv", "Raw CSV")

        partition = partition_annotations_df(df, result.deleted_images)
        self._write_partition_result(partition, output_dir)

    def _run_s3_sync(self, args: argparse.Namespace) -> None:
        """Run the ``s3-sync`` command."""
        cfg = self._load_config()
        self._require_host(cfg)

        ic_cfg = load_image_cache_config()
        if not ic_cfg.projects:
            sys.exit(
                "Ошибка: image_cache не настроен — нет проектов для синхронизации.\n"
                "Добавьте секцию image_cache в конфигурацию или запустите: cveta2 setup"
            )

        # Filter to a single project if --project was given
        if args.project:
            project_name = args.project.strip()
            cache_dir = ic_cfg.get_cache_dir(project_name)
            if cache_dir is None:
                sys.exit(
                    f"Ошибка: проект {project_name!r} не найден в image_cache.\n"
                    f"Настроенные проекты: "
                    f"{', '.join(ic_cfg.projects) or '(нет)'}"
                )
            projects_to_sync = {project_name: cache_dir}
        else:
            projects_to_sync = dict(ic_cfg.projects)

        cached = load_projects_cache()

        with CvatClient(cfg) as client:
            for project_name, cache_dir in projects_to_sync.items():
                logger.info(f"--- Синхронизация проекта: {project_name} ---")
                try:
                    project_id = client.resolve_project_id(project_name, cached=cached)
                except Cveta2Error as e:
                    logger.error(
                        f"Проект {project_name!r}: не удалось определить ID — {e}"
                    )
                    continue

                stats = client.sync_project_images(project_id, cache_dir)
                logger.info(
                    f"Проект {project_name!r}: {stats.downloaded} загружено, "
                    f"{stats.cached} из кэша, {stats.failed} ошибок "
                    f"(всего {stats.total})"
                )

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
        if args.command == "s3-sync":
            self._run_s3_sync(args)
            return
        sys.exit(f"Неизвестная команда: {args.command}")

    def run(self, argv: list[str] | None = None) -> None:
        """Run the CLI with the given arguments."""
        args = self._parser.parse_args(argv)
        self._run_command(args)


def main(argv: list[str] | None = None) -> None:
    """Compatibility entry point for setuptools/CLI wrappers."""
    CliApp().run(argv)


if __name__ == "__main__":
    main()

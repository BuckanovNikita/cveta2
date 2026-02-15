"""Implementation of the ``cveta2 upload`` command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import questionary
from loguru import logger

from cveta2.client import CvatClient
from cveta2.commands._helpers import load_config, require_host
from cveta2.config import (
    load_image_cache_config,
    load_upload_config,
    require_interactive,
)
from cveta2.exceptions import Cveta2Error
from cveta2.image_uploader import S3Uploader, resolve_images
from cveta2.projects_cache import load_projects_cache

if TYPE_CHECKING:
    import argparse

_NO_ANNOTATION_LABEL = "__no_annotation__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_dataset_csv(path: Path) -> pd.DataFrame:
    """Read and validate a dataset CSV file."""
    if not path.is_file():
        sys.exit(f"Ошибка: файл не найден: {path}")
    df = pd.read_csv(path, encoding="utf-8")
    if "image_name" not in df.columns or "instance_label" not in df.columns:
        sys.exit(
            "Ошибка: dataset.csv должен содержать столбцы "
            "'image_name' и 'instance_label'."
        )
    logger.info(f"Загружен {path}: {len(df)} строк")
    return df


def _read_exclude_names(in_progress_path: str | None) -> set[str]:
    """Read in_progress.csv and return image names to exclude."""
    if not in_progress_path:
        return set()
    ip_path = Path(in_progress_path)
    if not ip_path.is_file():
        sys.exit(f"Ошибка: файл не найден: {ip_path}")
    ip_df = pd.read_csv(ip_path, encoding="utf-8")
    if "image_name" not in ip_df.columns:
        return set()
    names: set[str] = set(ip_df["image_name"].dropna().unique())
    logger.info(f"Исключено {len(names)} изображений из in_progress.csv")
    return names


def _select_labels(df: pd.DataFrame) -> list[str]:
    """Interactively select instance labels from dataset.

    Includes a special "(без аннотаций)" choice when the dataset
    contains images without annotations (NaN ``instance_label``).
    The sentinel ``_NO_ANNOTATION_LABEL`` is returned in the list
    when that choice is selected.
    """
    all_labels = sorted(
        df["instance_label"].dropna().unique().tolist(),
    )
    has_no_annotation = df["instance_label"].isna().any()
    if not all_labels and not has_no_annotation:
        sys.exit("Ошибка: не найдено ни одного instance_label в dataset.csv.")
    require_interactive(
        "The 'upload' command requires interactive class selection.",
    )
    choices: list[questionary.Choice] = [
        questionary.Choice(title=label, value=label) for label in all_labels
    ]
    if has_no_annotation:
        choices.append(
            questionary.Choice(
                title="(без аннотаций)",
                value=_NO_ANNOTATION_LABEL,
            ),
        )
    selected: list[str] | None = questionary.checkbox(
        "Выберите классы для загрузки:",
        choices=choices,
    ).ask()
    if not selected:
        sys.exit("Не выбрано ни одного класса — отмена.")
    display = ["(без аннотаций)" if s == _NO_ANNOTATION_LABEL else s for s in selected]
    logger.info(
        f"Выбрано классов: {len(selected)}: {', '.join(display)}",
    )
    return selected


def _resolve_task_name(name_arg: str | None) -> str:
    """Return task name from argument or interactive prompt."""
    if name_arg:
        return name_arg
    require_interactive("Pass --name to specify the task name.")
    task_name = input("Имя задачи: ").strip()
    if not task_name:
        sys.exit("Имя задачи не указано — отмена.")
    return task_name


def _build_search_dirs(
    image_dir_arg: str | None,
    project_name: str,
) -> list[Path]:
    """Build list of directories to search for image files."""
    dirs: list[Path] = []
    if image_dir_arg:
        dirs.append(Path(image_dir_arg).resolve())
    ic_cfg = load_image_cache_config()
    cache_dir = ic_cfg.get_cache_dir(project_name)
    if cache_dir is not None:
        dirs.append(cache_dir)
    if not dirs:
        logger.warning(
            "Не указан --image-dir и не настроен image_cache "
            f"для проекта {project_name!r}. "
            "Будут загружены только изображения, "
            "уже находящиеся на S3.",
        )
    return dirs


def _resolve_upload_project(
    client: CvatClient,
    project_arg: str | None,
) -> tuple[int, str]:
    """Resolve project ID and name for the upload command."""
    if project_arg is not None:
        cached = load_projects_cache()
        try:
            project_id = client.resolve_project_id(
                project_arg.strip(),
                cached=cached,
            )
        except Cveta2Error as exc:
            sys.exit(str(exc))
        project_name = project_arg.strip()
    else:
        # Reuse the interactive project selector from the fetch command
        from cveta2.commands.fetch import (  # noqa: PLC0415
            _select_project_tui,
        )

        project_id = _select_project_tui(client)
        project_name = str(project_id)

    if project_name.isdigit():
        for p in load_projects_cache():
            if p.id == project_id:
                project_name = p.name
                break
    return project_id, project_name


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def run_upload(args: argparse.Namespace) -> None:
    """Run the ``upload`` command."""
    cfg = load_config()
    require_host(cfg)
    upload_cfg = load_upload_config()

    df = _read_dataset_csv(Path(args.dataset))
    exclude_names = _read_exclude_names(args.in_progress)
    selected_labels = _select_labels(df)

    # Filter and collect unique image names
    include_no_annotation = _NO_ANNOTATION_LABEL in selected_labels
    real_labels = [lbl for lbl in selected_labels if lbl != _NO_ANNOTATION_LABEL]
    mask = df["instance_label"].isin(real_labels)
    if include_no_annotation:
        mask = mask | df["instance_label"].isna()
    filtered = df[mask]
    image_names = set(filtered["image_name"].dropna().unique()) - exclude_names
    if not image_names:
        sys.exit("Ошибка: после фильтрации не осталось изображений.")
    logger.info(f"Изображений для загрузки: {len(image_names)}")

    task_name = _resolve_task_name(args.name)

    with CvatClient(cfg) as client:
        project_id, project_name = _resolve_upload_project(
            client,
            args.project,
        )
        search_dirs = _build_search_dirs(args.image_dir, project_name)
        found_images, missing = resolve_images(image_names, search_dirs)
        logger.info(
            f"Найдено локально: {len(found_images)}, не найдено: {len(missing)}",
        )

        cs_info = client.detect_project_cloud_storage(project_id)
        if cs_info is None:
            sys.exit(
                f"Ошибка: cloud storage не найден для проекта "
                f"{project_name!r} (id={project_id}).",
            )
        logger.info(
            f"Cloud storage: s3://{cs_info.bucket}/{cs_info.prefix} (id={cs_info.id})",
        )

        if found_images:
            stats = S3Uploader().upload(cs_info, found_images)
            logger.info(
                f"S3: {stats.uploaded} загружено, "
                f"{stats.skipped_existing} уже на S3, "
                f"{stats.failed} ошибок",
            )

        if missing:
            preview = ", ".join(missing[:10])
            extra = (
                f" (и ещё {len(missing) - 10})"
                if len(missing) > 10  # noqa: PLR2004
                else ""
            )
            logger.warning(
                f"{len(missing)} изображений не найдено локально: {preview}{extra}",
            )

        task_image_names = sorted(image_names)
        task_id = client.create_upload_task(
            project_id=project_id,
            name=task_name,
            image_names=task_image_names,
            cloud_storage_id=cs_info.id,
            segment_size=upload_cfg.images_per_job,
        )

        # Upload annotations from dataset.csv to the new task
        num_shapes = client.upload_task_annotations(
            task_id=task_id,
            annotations_df=filtered,
            image_names=task_image_names,
        )

        ipj = upload_cfg.images_per_job
        num_jobs = (len(task_image_names) + ipj - 1) // ipj
        logger.info(
            f"Задача создана: id={task_id}, "
            f"имя={task_name!r}, "
            f"изображений={len(task_image_names)}, "
            f"аннотаций={num_shapes}, "
            f"jobs≈{num_jobs} (segment_size={ipj})",
        )
        logger.info(f"URL: {cfg.host}/tasks/{task_id}")

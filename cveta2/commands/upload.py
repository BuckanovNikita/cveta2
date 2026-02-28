"""Implementation of the ``cveta2 upload`` command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import questionary
from loguru import logger

from cveta2.client import CvatClient
from cveta2.commands._helpers import (
    read_dataset_csv,
    require_host,
    resolve_project_or_exit,
)
from cveta2.config import (
    CvatConfig,
    load_image_cache_config,
    load_upload_config,
    require_interactive,
)
from cveta2.exceptions import LabelsMismatchError
from cveta2.image_uploader import S3Uploader, build_server_file_mapping, resolve_images
from cveta2.s3_utils import build_s3_key

if TYPE_CHECKING:
    import argparse

    from cveta2.image_downloader import CloudStorageInfo

_NO_ANNOTATION_LABEL = "__no_annotation__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_UPLOAD_REQUIRED_COLUMNS: set[str] = {"image_name", "instance_label"}


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


def _warn_missing_images(missing: list[str]) -> None:
    """Log a warning about images not found locally."""
    if not missing:
        return
    preview = ", ".join(missing[:10])
    extra = f" (и ещё {len(missing) - 10})" if len(missing) > 10 else ""
    logger.warning(
        f"{len(missing)} изображений не найдено локально: {preview}{extra}",
    )


def _enrich_paths(
    df: pd.DataFrame,
    cs_info: CloudStorageInfo,
    found_images: dict[str, Path],
    name_to_server_file: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Add ``s3_path`` and ``image_path`` columns to the DataFrame."""
    df = df.copy()
    df["s3_path"] = df["image_name"].map(
        lambda name: build_s3_key(
            cs_info.prefix,
            name_to_server_file[name]
            if name_to_server_file and name in name_to_server_file
            else name,
        )
    )
    df["image_path"] = df["image_name"].map(
        lambda name: str(found_images[name].resolve()) if name in found_images else None
    )
    return df


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def _validate_labels(
    client: CvatClient,
    project_id: int,
    project_name: str,
    real_labels: list[str],
) -> None:
    """Check that all CSV labels exist in the CVAT project."""
    if not real_labels:
        return
    project_labels = client.get_project_labels(project_id)
    project_label_names = {lbl.name for lbl in project_labels}
    unknown_labels = sorted(set(real_labels) - project_label_names)
    if unknown_labels:
        raise LabelsMismatchError(
            unknown_labels=unknown_labels,
            project_name=project_name,
            available_labels=sorted(project_label_names),
        )


def _extract_deleted_names(df: pd.DataFrame) -> set[str]:
    """Extract image names from rows with ``instance_shape="deleted"``."""
    if "instance_shape" not in df.columns:
        return set()
    mask = df["instance_shape"] == "deleted"
    names: set[str] = set(df.loc[mask, "image_name"].dropna().unique())
    if names:
        logger.info(f"Найдено удалённых изображений: {len(names)}")
    return names


def run_upload(args: argparse.Namespace) -> None:
    """Run the ``upload`` command."""
    cfg = CvatConfig.load()
    require_host(cfg)
    upload_cfg = load_upload_config()

    df = read_dataset_csv(Path(args.dataset), _UPLOAD_REQUIRED_COLUMNS)

    # Separate deleted rows before label selection
    deleted_names = _extract_deleted_names(df)
    deleted_mask = (
        (df["instance_shape"] == "deleted")
        if "instance_shape" in df.columns
        else pd.Series(data=False, index=df.index)
    )
    df_normal = df[~deleted_mask]

    exclude_names = _read_exclude_names(args.in_progress)
    selected_labels = _select_labels(df_normal)

    # Filter and collect unique image names
    include_no_annotation = _NO_ANNOTATION_LABEL in selected_labels
    real_labels = [lbl for lbl in selected_labels if lbl != _NO_ANNOTATION_LABEL]
    mask = df_normal["instance_label"].isin(real_labels)
    if include_no_annotation:
        mask = mask | df_normal["instance_label"].isna()
    filtered = df_normal[mask]
    image_names = set(filtered["image_name"].dropna().unique()) - exclude_names
    if not image_names and not deleted_names:
        sys.exit("Ошибка: после фильтрации не осталось изображений.")
    logger.info(f"Изображений для загрузки: {len(image_names)}")

    all_image_names = image_names | deleted_names
    task_name = _resolve_task_name(args.name)

    with CvatClient(cfg) as client:
        project_id, project_name = resolve_project_or_exit(
            args.project,
            client,
        )

        _validate_labels(client, project_id, project_name, real_labels)

        search_dirs = _build_search_dirs(args.image_dir, project_name)
        found_images, missing = resolve_images(all_image_names, search_dirs)
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

        name_to_server_file, existing_keys = build_server_file_mapping(
            cs_info,
            all_image_names,
        )

        filtered = _enrich_paths(filtered, cs_info, found_images, name_to_server_file)

        if found_images:
            stats = S3Uploader().upload(
                cs_info,
                found_images,
                name_to_server_file,
                existing_keys,
            )
            logger.info(
                f"S3: {stats.uploaded} загружено, "
                f"{stats.skipped_existing} уже на S3, "
                f"{stats.failed} ошибок",
            )

        _warn_missing_images(missing)

        task_image_names = sorted(name_to_server_file[n] for n in all_image_names)
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
        )

        if deleted_names:
            client.mark_frames_deleted(task_id, deleted_names)

        if args.complete:
            client.complete_task(task_id)

        ipj = upload_cfg.images_per_job
        num_jobs = (len(task_image_names) + ipj - 1) // ipj
        logger.info(
            f"Задача создана: id={task_id}, "
            f"имя={task_name!r}, "
            f"изображений={len(task_image_names)}, "
            f"удалённых={len(deleted_names)}, "
            f"аннотаций={num_shapes}, "
            f"jobs≈{num_jobs} (segment_size={ipj})",
        )
        logger.info(f"URL: {cfg.host}/tasks/{task_id}")

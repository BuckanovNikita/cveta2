"""CLI adapter for the ``cveta2 upload`` command.

Only argument mapping, interactive prompts and ``sys.exit`` UX live here;
the pipeline itself is :mod:`cveta2.services.upload`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import questionary
from loguru import logger

from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import read_dataset_csv, resolve_project_or_exit
from cveta2.config import load_upload_config, require_interactive
from cveta2.exceptions import Cveta2Error
from cveta2.services.upload import (
    UploadOptions,
    build_search_dirs,
    build_upload_plan,
    read_exclude_names,
    split_deleted_rows,
    upload_dataset,
)

if TYPE_CHECKING:
    import argparse

    import pandas as pd

_NO_ANNOTATION_LABEL = "__no_annotation__"

_UPLOAD_REQUIRED_COLUMNS: set[str] = {"image_name", "instance_label"}


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


def run_upload(args: argparse.Namespace) -> None:
    """Run the ``upload`` command."""
    upload_cfg = load_upload_config()

    df = read_dataset_csv(Path(args.dataset), _UPLOAD_REQUIRED_COLUMNS)
    df_normal, deleted_names = split_deleted_rows(df)

    try:
        exclude_names = read_exclude_names(args.in_progress)
        selected = _select_labels(df_normal)
        plan = build_upload_plan(
            df_normal,
            deleted_names,
            labels=[lbl for lbl in selected if lbl != _NO_ANNOTATION_LABEL],
            include_unannotated=_NO_ANNOTATION_LABEL in selected,
            exclude_names=exclude_names,
        )
    except Cveta2Error as e:
        sys.exit(str(e))

    task_name = _resolve_task_name(args.name)

    with open_client() as client:
        project_id, project_name = resolve_project_or_exit(
            args.project,
            client,
        )
        options = UploadOptions(
            search_dirs=build_search_dirs(args.image_dir, project_name),
            segment_size=upload_cfg.images_per_job,
            image_quality=upload_cfg.image_quality,
            mark_all_deleted=args.mark_all_deleted,
            complete=args.complete,
        )
        try:
            upload_dataset(client, project_id, project_name, plan, task_name, options)
        except Cveta2Error as e:
            sys.exit(str(e))

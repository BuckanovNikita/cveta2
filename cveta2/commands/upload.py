"""CLI adapter for the ``cveta2 upload`` command.

Only argument mapping and interactive prompts live here;
the pipeline itself is :mod:`cveta2.services.upload`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands import interactive
from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import echo_cli_command, resolve_project
from cveta2.config import UploadConfig
from cveta2.exceptions import Cveta2Error
from cveta2.services.output import read_dataset_csv
from cveta2.services.upload import (
    UploadOptions,
    UploadRequest,
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
        raise Cveta2Error("Ошибка: не найдено ни одного instance_label в dataset.csv.")
    choices: list[interactive.Choice] = [
        interactive.Choice(title=label, value=label) for label in all_labels
    ]
    if has_no_annotation:
        choices.append(
            interactive.Choice(
                title="(без аннотаций)",
                value=_NO_ANNOTATION_LABEL,
            ),
        )
    raw = interactive.select_many(
        "Выберите классы для загрузки:",
        choices,
        hint="The 'upload' command requires interactive class selection.",
        empty_message="Не выбрано ни одного класса — отмена.",
    )
    selected = [str(v) for v in raw or []]
    display = ["(без аннотаций)" if s == _NO_ANNOTATION_LABEL else s for s in selected]
    logger.info(
        f"Выбрано классов: {len(selected)}: {', '.join(display)}",
    )
    return selected


def _resolve_labels(labels_arg: list[str] | None, df: pd.DataFrame) -> list[str]:
    """Return selected labels from ``--labels`` or the interactive picker.

    Labels passed on the command line are validated against the dataset
    (including the ``__no_annotation__`` sentinel when the dataset has
    frames without annotations).
    """
    if labels_arg is None:
        return _select_labels(df)
    available = set(df["instance_label"].dropna().unique().tolist())
    if df["instance_label"].isna().any():
        available.add(_NO_ANNOTATION_LABEL)
    unknown = sorted(set(labels_arg) - available)
    if unknown:
        raise Cveta2Error(
            f"Ошибка: метки не найдены в dataset.csv: {', '.join(unknown)}.\n"
            f"Доступные: {', '.join(sorted(available))}"
        )
    return list(labels_arg)


def _resolve_task_name(name_arg: str | None) -> str:
    """Return task name from argument or interactive prompt."""
    if name_arg:
        return name_arg
    task_name = interactive.text(
        "Имя задачи: ",
        hint="Pass --name to specify the task name.",
        allow_empty=False,
        empty_message="Имя задачи не указано — отмена.",
        history_key="task-name",
    )
    return str(task_name)


def run_upload(args: argparse.Namespace) -> None:
    """Run the ``upload`` command."""
    upload_cfg = UploadConfig.load()

    df = read_dataset_csv(Path(args.dataset), _UPLOAD_REQUIRED_COLUMNS)
    df_normal, deleted_names = split_deleted_rows(df)

    exclude_names = read_exclude_names(args.in_progress)

    prompted = not args.project or not args.name or args.labels is None

    with open_client() as client:
        project_id, project_name = resolve_project(client, args.project)
        task_name = _resolve_task_name(args.name)
        selected = _resolve_labels(args.labels, df_normal)
        if prompted:
            echo_cli_command(
                "upload",
                {
                    "-p": project_name,
                    "-d": args.dataset,
                    "--labels": selected,
                    "--in-progress": args.in_progress,
                    "--image-dir": args.image_dir,
                    "--name": task_name,
                    "--complete": args.complete,
                    "--mark-all-deleted": args.mark_all_deleted,
                },
            )
        plan = build_upload_plan(
            df_normal,
            deleted_names,
            labels=[lbl for lbl in selected if lbl != _NO_ANNOTATION_LABEL],
            include_unannotated=_NO_ANNOTATION_LABEL in selected,
            exclude_names=exclude_names,
        )
        options = UploadOptions(
            search_dirs=build_search_dirs(
                [args.image_dir] if args.image_dir else None, project_name
            ),
            segment_size=upload_cfg.images_per_job,
            image_quality=upload_cfg.image_quality,
            mark_all_deleted=args.mark_all_deleted,
            complete=args.complete,
        )
        request = UploadRequest(
            project_id=project_id,
            project_name=project_name,
            task_name=task_name,
            plan=plan,
            options=options,
        )
        upload_dataset(client, request)

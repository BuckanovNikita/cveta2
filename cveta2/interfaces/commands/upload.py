"""CLI adapter for the ``cveta2 upload`` command.

Only argument mapping and interactive prompts live here;
the pipeline itself is :mod:`cveta2.application.use_cases.upload`.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.application.use_cases.upload import (
    UPLOAD_REQUIRED_COLUMNS,
    UploadOptions,
    UploadRequest,
    build_upload_plan,
    split_deleted_rows,
)
from cveta2.composition.configuration import UploadConfig
from cveta2.composition.files import read_dataset_csv
from cveta2.composition.workflows import (
    build_search_dirs,
    read_exclude_names,
    upload_cvat_dataset,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.interfaces.commands import interactive
from cveta2.interfaces.commands._bootstrap import open_client
from cveta2.interfaces.commands._helpers import (
    echo_if_prompted,
    project_cli_spec,
    resolve_project,
)
from cveta2.interfaces.commands._parsers import add_project_arg

if TYPE_CHECKING:
    import argparse

    import pandas as pd

_NO_ANNOTATION_LABEL = "__no_annotation__"
_NO_ANNOTATION_TITLE = "(без аннотаций)"

# Presentation-only literals live at module level so mutation testing does not
# generate unkillable "change the caption" mutants inside the functions below.
_LABEL_DISPLAY = {_NO_ANNOTATION_LABEL: _NO_ANNOTATION_TITLE}
_NO_LABELS_ERROR = "Ошибка: не найдено ни одного instance_label в dataset.csv."
_LABELS_PROMPT = "Выберите классы для загрузки:"
_LABELS_HINT = "Pass --labels to select classes non-interactively."
_LABELS_EMPTY_MESSAGE = "Не выбрано ни одного класса — отмена."
_TASK_NAME_PROMPT = "Имя задачи: "
_TASK_NAME_HINT = "Pass --name to specify the task name."
_TASK_NAME_EMPTY_MESSAGE = "Имя задачи не указано — отмена."
_TASK_NAME_HISTORY_KEY = "task-name"


def configure_upload(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``upload`` command arguments."""
    add_project_arg(parser)
    parser.add_argument(
        "--dataset",
        "-d",
        required=True,
        help="Path to dataset.csv produced by the fetch command.",
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        type=str,
        default=None,
        metavar="LABEL",
        help=(
            "Instance labels selecting frames to upload "
            "(use __no_annotation__ for frames without annotations; "
            "'--labels all' selects every label). "
            "If omitted, interactive selection is shown."
        ),
    )
    parser.add_argument(
        "--in-progress",
        type=str,
        default=None,
        help=(
            "Path to in_progress.csv — images listed there "
            "will be excluded from the upload."
        ),
    )
    parser.add_argument(
        "--image-dir",
        type=str,
        default=None,
        help="Additional directory to search for image files.",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Task name. If omitted, prompted interactively.",
    )
    parser.add_argument(
        "--complete",
        action="store_true",
        help="Mark the task as completed after upload.",
    )
    parser.add_argument(
        "--mark-all-deleted",
        action="store_true",
        help="Mark every uploaded image as deleted after task creation.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Continue the last unfinished upload of this dataset instead of "
            "creating a second task. Pass the same --dataset and --labels."
        ),
    )


def _available_labels(df: "pd.DataFrame") -> tuple[list[str], bool]:
    """Sorted dataset labels + whether frames without annotations exist."""
    labels = sorted(df["instance_label"].dropna().unique().tolist())
    has_no_annotation = bool(df["instance_label"].isna().any())
    return labels, has_no_annotation


def _select_labels(df: "pd.DataFrame", *, has_deleted: bool = False) -> list[str]:
    """Interactively select instance labels from dataset.

    Includes a special "(без аннотаций)" choice when the dataset
    contains images without annotations (NaN ``instance_label``).
    The sentinel ``_NO_ANNOTATION_LABEL`` is returned in the list
    when that choice is selected.

    A dataset that offers no class at all is an error only when it has
    nothing else to upload: with *has_deleted* set, the CSV consists of
    deleted frames, which the pipeline uploads without any label.
    """
    all_labels, has_no_annotation = _available_labels(df)
    if not all_labels and not has_no_annotation:
        if not has_deleted:
            raise Cveta2Error(_NO_LABELS_ERROR)
        logger.info("В CSV только удалённые кадры — выбор классов пропущен")
        return []
    choices: list[interactive.Choice] = [
        interactive.Choice(title=label, value=label) for label in all_labels
    ]
    if has_no_annotation:
        choices.append(
            interactive.Choice(
                title=_NO_ANNOTATION_TITLE,
                value=_NO_ANNOTATION_LABEL,
            ),
        )
    raw = interactive.select_many(
        _LABELS_PROMPT,
        choices,
        hint=_LABELS_HINT,
        empty_message=_LABELS_EMPTY_MESSAGE,
    )
    selected = [str(v) for v in raw or []]
    logger.info(
        f"Выбрано классов: {len(selected)}: "
        f"{', '.join(_LABEL_DISPLAY.get(s, s) for s in selected)}",
    )
    return selected


def _resolve_labels(
    labels_arg: list[str] | None,
    df: "pd.DataFrame",
    *,
    has_deleted: bool = False,
) -> list[str]:
    """Return selected labels from ``--labels`` or the interactive picker.

    ``--labels all`` selects every dataset label (plus frames without
    annotations, unless the dataset really has a label named ``all``).
    Other labels passed on the command line are validated against the
    dataset (including the ``__no_annotation__`` sentinel when the
    dataset has frames without annotations).
    """
    if labels_arg is None:
        return _select_labels(df, has_deleted=has_deleted)
    labels, has_no_annotation = _available_labels(df)
    available = set(labels)
    if has_no_annotation:
        available.add(_NO_ANNOTATION_LABEL)
    if list(labels_arg) == ["all"] and "all" not in available:
        selected = list(labels)
        if has_no_annotation:
            selected.append(_NO_ANNOTATION_LABEL)
        logger.info(f"--labels all: выбраны все классы ({len(selected)})")
        return selected
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
        _TASK_NAME_PROMPT,
        hint=_TASK_NAME_HINT,
        allow_empty=False,
        empty_message=_TASK_NAME_EMPTY_MESSAGE,
        history_key=_TASK_NAME_HISTORY_KEY,
    )
    return str(task_name)


def run_upload(args: "argparse.Namespace") -> None:
    """Run the ``upload`` command."""
    upload_cfg = UploadConfig.load()

    df = read_dataset_csv(Path(args.dataset), UPLOAD_REQUIRED_COLUMNS)
    df_normal, deleted_names = split_deleted_rows(df)

    exclude_names = read_exclude_names(args.in_progress)

    prompted = not args.project or not args.name or args.labels is None

    with open_client() as client:
        project_id, project_name = resolve_project(client, args.project)
        task_name = _resolve_task_name(args.name)
        selected = _resolve_labels(
            args.labels, df_normal, has_deleted=bool(deleted_names)
        )
        echo_if_prompted(
            "upload",
            {
                "-p": project_cli_spec(client, project_name),
                "-d": args.dataset,
                "--labels": selected,
                "--in-progress": args.in_progress,
                "--image-dir": args.image_dir,
                "--name": task_name,
                "--complete": args.complete,
                "--mark-all-deleted": args.mark_all_deleted,
                "--resume": args.resume,
            },
            prompted=prompted,
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
            dataset_path=str(args.dataset),
            labels=tuple(selected),
            resume=args.resume,
        )
        upload_cvat_dataset(client, request)

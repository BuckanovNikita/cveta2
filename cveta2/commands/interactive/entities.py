"""Domain-entity pickers: projects, tasks, labels.

These build questionary choices from domain objects and delegate the actual
prompting to :mod:`cveta2.commands.interactive.primitives`.  They are the
single shared implementation for selecting projects/tasks/labels, replacing
the previously duplicated pickers in ``_helpers``, ``_task_selector``,
``ignore`` and ``labels``.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, cast

from loguru import logger

from cveta2.commands.interactive import primitives
from cveta2.commands.interactive._questionary import Choice
from cveta2.projects_cache import (
    PERSONAL_WORKSPACE_SLUG,
    PERSONAL_WORKSPACE_TITLE,
    OrgProjects,
    load_orgs_cache,
    save_orgs_cache,
)

if TYPE_CHECKING:
    from cveta2.client import CvatClient
    from cveta2.models import LabelInfo, TaskInfo

_RESCAN_VALUE = "__rescan__"
_NEXT_ORG_VALUE = "__next_org__"

_PROJECT_HINT = "Pass --project / -p to specify the project ID or name."
_PROJECT_NAME_HINT = "Pass --project / -p to specify the project name."
_TASK_HINT = "Pass task ID(s) or name(s) with --task / -t to specify task(s)."


def _as_int_ids(values: list[object] | None) -> set[int]:
    """Coerce picker values (typed as ``object``) to a set of task/label ids."""
    return {cast("int", v) for v in values or []}


def build_task_choices(tasks: list[TaskInfo]) -> list[Choice]:
    """Build questionary choices from a task list."""
    return [Choice(title=t.format_display(), value=t.id) for t in tasks]


def _scan_organizations(client: CvatClient) -> list[OrgProjects]:
    """Fetch projects of every organization (plus the personal workspace).

    Restores the client's session organization after scanning.
    """
    original_org = client.organization
    pages = [
        OrgProjects(
            slug=PERSONAL_WORKSPACE_SLUG,
            name=PERSONAL_WORKSPACE_TITLE,
            projects=[],
        )
    ]
    pages.extend(
        OrgProjects(slug=org.slug, name=org.name, projects=[])
        for org in client.list_organizations()
    )
    scanned: list[OrgProjects] = []
    for page in pages:
        client.set_organization(page.slug or None)
        scanned.append(page.model_copy(update={"projects": client.list_projects()}))
    client.set_organization(original_org)
    total = sum(len(page.projects) for page in scanned)
    logger.info(f"Загружено проектов: {total} (организаций: {len(scanned)})")
    return scanned


def _order_org_pages(pages: list[OrgProjects], first_slug: str) -> list[OrgProjects]:
    """Put the *first_slug* page first, keeping the rest in listing order."""
    first = [page for page in pages if page.slug == first_slug]
    rest = [page for page in pages if page.slug != first_slug]
    return first + rest


def select_project(client: CvatClient) -> tuple[int, str]:
    """Interactive project selection, one page per organization.

    The first page is the configured default organization (or the
    personal workspace).  Selecting a project switches the client's
    session organization to that page's org.  Returns
    ``(project_id, project_name)``.
    """
    default_slug = client.organization or PERSONAL_WORKSPACE_SLUG
    pages = load_orgs_cache()
    if not pages:
        logger.info("Кэш проектов пуст. Загружаю список с CVAT...")
        pages = _scan_organizations(client)
        save_orgs_cache(pages)
    index = 0
    while True:
        pages = _order_org_pages(pages, default_slug)
        if not any(page.projects for page in pages):
            sys.exit("Нет доступных проектов.")
        page = pages[index % len(pages)]
        answer = _ask_project_page(page, pages, index)
        if answer == _NEXT_ORG_VALUE:
            index += 1
            continue
        if answer == _RESCAN_VALUE:
            pages = _scan_organizations(client)
            save_orgs_cache(pages)
            index = 0
            continue
        project_id = cast("int", answer)
        client.set_organization(page.slug or None)
        project_name = next(
            (p.name for p in page.projects if p.id == project_id),
            str(project_id),
        )
        return (project_id, project_name)


def _ask_project_page(
    page: OrgProjects,
    pages: list[OrgProjects],
    index: int,
) -> object:
    """Prompt for a project on one org page; return id or a nav sentinel."""
    choices = [Choice(title=f"{p.name} (id={p.id})", value=p.id) for p in page.projects]
    if len(pages) > 1:
        next_page = pages[(index + 1) % len(pages)]
        choices.append(
            Choice(
                title=f"→ Следующая организация: {next_page.name}",
                value=_NEXT_ORG_VALUE,
            ),
        )
    choices.append(
        Choice(title="↻ Обновить список проектов с CVAT", value=_RESCAN_VALUE),
    )
    return primitives.select_one(
        f"Выберите проект — {page.name}:",
        choices,
        hint=_PROJECT_HINT,
    )


def select_project_name(names: list[str]) -> str:
    """Select a project by name from a known-names list.  Exits on cancel."""
    if not names:
        sys.exit(
            "Нет известных проектов. "
            "Укажите --project или запустите cveta2 fetch для заполнения кэша."
        )
    choices = [Choice(title=name, value=name) for name in names]
    answer = primitives.select_one("Выберите проект:", choices, hint=_PROJECT_NAME_HINT)
    return str(answer)


def select_tasks(
    client: CvatClient,
    project_id: int,
    exclude_ids: set[int] | None = None,
) -> list[TaskInfo]:
    """Interactive multi-task selection.  Exits on cancel or empty selection.

    Returns full ``TaskInfo`` objects so callers can access ``.id`` and ``.name``.
    Tasks whose IDs are in *exclude_ids* are hidden from the list.
    """
    tasks = client.list_project_tasks(project_id)
    if exclude_ids:
        tasks = [t for t in tasks if t.id not in exclude_ids]
    if not tasks:
        sys.exit("Нет доступных задач в этом проекте.")

    answer = primitives.select_many(
        "Выберите задачу (задачи):",
        build_task_choices(tasks),
        hint=_TASK_HINT,
        empty_message="Задачи не выбраны.",
    )
    selected_ids = _as_int_ids(answer)
    tasks_by_id = {t.id: t for t in tasks}
    return [tasks_by_id[tid] for tid in selected_ids if tid in tasks_by_id]


def pick_tasks(tasks: list[TaskInfo], *, message: str) -> list[TaskInfo]:
    """Multi-task checkbox that returns ``[]`` on cancel (for CRUD loops).

    Unlike :func:`select_tasks`, a cancel or empty selection returns an empty
    list instead of terminating the program, so an interactive loop continues.
    """
    answer = primitives.select_many(
        message,
        build_task_choices(tasks),
        hint=_TASK_HINT,
        on_cancel="none",
        allow_empty=True,
    )
    selected_ids = _as_int_ids(answer)
    tasks_by_id = {t.id: t for t in tasks}
    return [tasks_by_id[tid] for tid in selected_ids if tid in tasks_by_id]


def select_label(labels: list[LabelInfo], *, message: str) -> int | None:
    """Pick a single label by display name.  Returns its id or ``None``."""
    sorted_labels = sorted(labels, key=lambda lbl: lbl.name)
    choices = [
        Choice(title=lbl.format_display(), value=lbl.id) for lbl in sorted_labels
    ]
    answer = primitives.select_one(
        message,
        choices,
        hint="Pass --list to view labels non-interactively.",
        on_cancel="none",
    )
    return None if answer is None else cast("int", answer)


def select_labels(labels: list[LabelInfo], *, message: str) -> list[int]:
    """Pick multiple labels by display name.  Returns ids (``[]`` on cancel)."""
    sorted_labels = sorted(labels, key=lambda lbl: lbl.name)
    choices = [
        Choice(title=lbl.format_display(), value=lbl.id) for lbl in sorted_labels
    ]
    answer = primitives.select_many(
        message,
        choices,
        hint="Pass --list to view labels non-interactively.",
        on_cancel="none",
        allow_empty=True,
    )
    return sorted(_as_int_ids(answer))

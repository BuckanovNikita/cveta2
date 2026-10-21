"""Public project/task fetch inputs and cache/image option resolution."""

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from cveta2.application.use_cases.fetch import FetchOptions, FetchTarget
from cveta2.application.use_cases.resolve import (
    infer_project_from_tasks,
    resolve_project_spec,
)
from cveta2.composition.client import CvatClient
from cveta2.composition.configuration import resolve_images_cache_dir
from cveta2.composition.workflows import (
    fetch_project,
    fetch_selected_tasks,
    load_ignore_sets,
    project_cloud_storage,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import CSV_COLUMNS
from cveta2.interfaces.api.connection import _config_path, _open

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cveta2.domain.partition import PartitionResult
    from cveta2.interfaces.api.types import CacheMode, Connection

_CACHE_FLAGS: dict[str, tuple[bool, bool]] = {
    "use": (True, False),
    "refresh": (True, True),
    "off": (False, False),
}

# Fixed user-facing prose contains no policy; keep it outside mutation targets.
_ERR_IMAGES_DIR_CONFLICT = (
    "Параметры несовместимы: передан images_dir= при download_images=False."
)
_ERR_PROJECT_UNRESOLVED = (
    "Не удалось определить проект: передайте project= или укажите задачи числовыми ID."
)


def _cache_flags(cache: "CacheMode") -> tuple[bool, bool]:
    """Map a cache mode onto the ``(use_cache, force)`` fetch options."""
    try:
        return _CACHE_FLAGS[cache]
    except KeyError:
        raise Cveta2Error(
            f"Недопустимое значение cache={cache!r}; допустимые: use, refresh, off."
        ) from None


def _resolve_fetch_target(
    client: CvatClient,
    project: int | str,
    output_dir: Path,
    config_path: Path | None,
) -> tuple[FetchTarget, set[int] | None, set[int] | None]:
    """Resolve project, cloud storage and ignore sets for a fetch.

    Shared by ``fetch`` and ``fetch_task``, which resolved the identical
    three steps. Deliberately not shared with ``commands/fetch.py``: that
    layer resolves the project interactively first, and re-resolving from
    a bare name here would lose the sync-root and TUI paths.
    """
    project_id, project_name = resolve_project_spec(client, project)
    cs_info = project_cloud_storage(
        client, project_id, project_name, config_path=config_path
    )
    ignore_set, silent_set = load_ignore_sets(project_name, config_path)
    target = FetchTarget(project_id, project_name, output_dir, cs_info)
    return target, ignore_set, silent_set


def _resolve_images_dir(
    images_dir: str | Path | None,
    download_images: bool,  # noqa: FBT001
    project_name: str,
    config_path: Path | None,
) -> Path | None:
    """Resolve the image download directory without prompting."""
    if images_dir and not download_images:
        raise Cveta2Error(_ERR_IMAGES_DIR_CONFLICT)
    if not download_images:
        return None
    if images_dir:
        return Path(images_dir).resolve()
    configured = resolve_images_cache_dir(project_name, config_path)
    if configured is not None:
        return configured
    raise Cveta2Error(
        f"Путь кэширования изображений для проекта {project_name!r} не "
        f"настроен. Передайте images_dir=, download_images=False или "
        f"добавьте image_cache.{project_name} (или cache.images_root) "
        f"в конфигурацию."
    )


def fetch(  # noqa: PLR0913
    project: int | str,
    output_dir: str | Path,
    *,
    completed_only: bool = False,
    skip_validation: bool = False,
    raw: bool = False,
    images_dir: str | Path | None = None,
    download_images: bool = True,
    cache: "CacheMode" = "use",
    save_tasks: bool = False,
    connection: "Connection | None" = None,
) -> "PartitionResult":
    """Fetch a whole project like ``cveta2 fetch``.

    Writes dataset/obsolete/in_progress/deleted CSVs (plus raw.csv when
    *raw*) into *output_dir* and returns the full
    :class:`~cveta2.domain.partition.PartitionResult` — the
    ``dataset`` / ``obsolete`` / ``in_progress`` DataFrames plus
    ``deleted_images``.  DataFrame columns follow
    :data:`cveta2.CSV_COLUMNS`; rows are flattened
    :data:`cveta2.AnnotationRecord` variants (see
    ``specs/baseline.md``).

    *cache* controls the task-annotation cache: ``"use"`` reads and
    updates it, ``"refresh"`` re-downloads every task and updates it,
    ``"off"`` disables it entirely.

    *skip_validation* accepts eligible completed annotation jobs in CVAT
    before fetching fresh task metadata, including for *completed_only*.
    A promotion failure aborts the export and retains successful changes.

    *project* (here and in every function taking a project spec) accepts
    an id, a name, or ``"ORG/PROJECT"`` — the org prefix overrides the
    configured organization (``"/PROJECT"`` selects the personal
    workspace).
    """
    use_cache, force = _cache_flags(cache)
    config_path = _config_path(connection)
    with _open(connection) as c:
        resolved, ignore_set, silent_set = _resolve_fetch_target(
            c, project, Path(output_dir), config_path
        )
        options = FetchOptions(
            completed_only=completed_only,
            skip_validation=skip_validation,
            ignore_task_ids=ignore_set,
            silent_task_ids=silent_set,
            use_cache=use_cache,
            force=force,
            save_tasks=save_tasks,
            images_dir=_resolve_images_dir(
                images_dir, download_images, resolved.project_name, config_path
            ),
            raw=raw,
            config_path=config_path,
        )
        return fetch_project(c, resolved, options)


def fetch_task(  # noqa: PLR0913
    tasks: "Sequence[int | str]",
    output_dir: str | Path,
    *,
    project: int | str | None = None,
    completed_only: bool = False,
    images_dir: str | Path | None = None,
    download_images: bool = True,
    cache: "CacheMode" = "use",
    save_tasks: bool = False,
    connection: "Connection | None" = None,
) -> "pd.DataFrame":
    """Fetch selected tasks like ``cveta2 fetch-task``.

    Writes dataset.csv and deleted.csv into *output_dir* and returns all
    fetched rows as a DataFrame with :data:`cveta2.CSV_COLUMNS` columns
    (unpartitioned, unlike :func:`fetch`).  *cache* works as in
    :func:`fetch`.

    *project* accepts an id, a name, or ``"ORG/PROJECT"``; when omitted,
    it is inferred from the first numeric task id in *tasks* (task names
    alone cannot be resolved without a project).
    """
    use_cache, force = _cache_flags(cache)
    config_path = _config_path(connection)
    with _open(connection) as c:
        if project is None:
            project = infer_project_from_tasks(c, tasks)
            if project is None:
                raise Cveta2Error(_ERR_PROJECT_UNRESOLVED)
        resolved, ignore_set, silent_set = _resolve_fetch_target(
            c, project, Path(output_dir), config_path
        )
        options = FetchOptions(
            completed_only=completed_only,
            task_selector=list(tasks),
            ignore_task_ids=ignore_set,
            silent_task_ids=silent_set,
            use_cache=use_cache,
            force=force,
            save_tasks=save_tasks,
            images_dir=_resolve_images_dir(
                images_dir, download_images, resolved.project_name, config_path
            ),
            config_path=config_path,
        )
        result = fetch_selected_tasks(c, resolved, options)
    return pd.DataFrame(result.to_csv_rows(), columns=list(CSV_COLUMNS))

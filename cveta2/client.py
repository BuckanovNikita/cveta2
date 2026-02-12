"""CVAT client logic: connect, fetch annotations, extract shapes."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pandas as pd
from cvat_sdk import make_client  # type: ignore[import-untyped]
from loguru import logger

from cveta2._client.context import _TaskContext
from cveta2._client.extractors import _collect_shapes
from cveta2._client.mapping import _build_label_maps
from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.config import CvatConfig
from cveta2.models import (
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
)
from cveta2.projects_cache import ProjectInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from cveta2._client.ports import CvatApiPort


class CvatClient:
    """High-level CVAT client that fetches bbox annotations."""

    def __init__(
        self,
        cfg: CvatConfig,
        client_factory: Callable[..., Any] | None = None,
        *,
        api: CvatApiPort | None = None,
    ) -> None:
        """Store client configuration and optional API port for DI.

        When *api* is provided it is used directly.  Otherwise an
        ``SdkCvatApiAdapter`` is created on the fly from an SDK client
        opened via *client_factory*.
        """
        self._cfg = cfg
        self._client_factory = client_factory or make_client
        self._api = api

    # ------------------------------------------------------------------
    # SDK client lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def _open_sdk_adapter(self) -> Iterator[SdkCvatApiAdapter]:
        """Open an SDK client and yield an adapter wrapping it."""
        resolved = self._cfg.ensure_credentials()
        kwargs = self._build_client_kwargs(resolved)
        with self._client_factory(**kwargs) as sdk_client:
            if resolved.organization:
                sdk_client.organization_slug = resolved.organization
                logger.trace(
                    f"Using organization: {resolved.organization}",
                )
            yield SdkCvatApiAdapter(sdk_client)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_projects(self) -> list[ProjectInfo]:
        """Fetch list of projects from CVAT (id and name)."""
        if self._api is not None:
            raw = self._api.list_projects()
            return [ProjectInfo(id=p.id, name=p.name) for p in raw]
        with self._open_sdk_adapter() as api:
            raw = api.list_projects()
            return [ProjectInfo(id=p.id, name=p.name) for p in raw]

    def resolve_project_id(
        self,
        project_spec: int | str,
        *,
        cached: list[ProjectInfo] | None = None,
    ) -> int:
        """Resolve project id from numeric id or project name.

        If project_spec is int or digit string, returns it as int.
        If it is a name, looks in cached list first, then via API.
        """
        if isinstance(project_spec, int):
            return project_spec
        s = str(project_spec).strip()
        if s.isdigit():
            return int(s)
        search = s.casefold()
        if cached:
            for p in cached:
                if (p.name or "").casefold() == search:
                    return p.id
        projects = self.list_projects()
        for p in projects:
            if (p.name or "").casefold() == search:
                return p.id
        raise ValueError(f"Project not found: {s!r}")

    def fetch_annotations(
        self,
        project_id: int,
        *,
        completed_only: bool = False,
    ) -> ProjectAnnotations:
        """Fetch all bbox annotations and deleted images from a project.

        If ``completed_only`` is True, only completed tasks are processed.
        """
        if self._api is not None:
            return self._fetch_annotations(
                self._api,
                project_id,
                completed_only=completed_only,
            )
        with self._open_sdk_adapter() as api:
            return self._fetch_annotations(
                api,
                project_id,
                completed_only=completed_only,
            )

    # ------------------------------------------------------------------
    # Core annotation logic (single code path for all API backends)
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_annotations(
        api: CvatApiPort,
        project_id: int,
        *,
        completed_only: bool = False,
    ) -> ProjectAnnotations:
        """Fetch annotations through a ``CvatApiPort`` implementation."""
        tasks = api.get_project_tasks(project_id)
        labels = api.get_project_labels(project_id)
        label_names, attr_names = _build_label_maps(labels)

        if completed_only:
            tasks = [t for t in tasks if t.status == "completed"]
            logger.trace(f"Filtered to {len(tasks)} completed task(s)")
        if not tasks:
            logger.warning("No tasks in this project.")
            return ProjectAnnotations(
                annotations=[],
                deleted_images=[],
            )

        all_annotations: list[BBoxAnnotation] = []
        all_deleted: list[DeletedImage] = []
        all_without: list[ImageWithoutAnnotations] = []

        for task in tasks:
            data_meta = api.get_task_data_meta(task.id)
            annotations = api.get_task_annotations(task.id)

            ctx = _TaskContext.from_raw(
                task,
                data_meta,
                label_names,
                attr_names,
            )
            task_annotations = _collect_shapes(
                annotations.shapes,
                ctx,
            )

            deleted_ids = set(data_meta.deleted_frames)
            frames = ctx.frames
            task_deleted = [
                DeletedImage(
                    task_id=task.id,
                    task_name=task.name,
                    task_status=task.status,
                    task_updated_date=task.updated_date,
                    frame_id=fid,
                    image_name=(frames[fid].name if fid in frames else "<unknown>"),
                )
                for fid in data_meta.deleted_frames
            ]

            annotated_ids = {a.frame_id for a in task_annotations}
            task_without = [
                ImageWithoutAnnotations(
                    image_name=frame.name,
                    image_width=frame.width,
                    image_height=frame.height,
                    task_id=task.id,
                    task_name=task.name,
                    task_status=task.status,
                    task_updated_date=task.updated_date,
                    frame_id=fid,
                    subset=task.subset,
                )
                for fid, frame in frames.items()
                if fid not in deleted_ids and fid not in annotated_ids
            ]

            all_annotations.extend(task_annotations)
            all_deleted.extend(task_deleted)
            all_without.extend(task_without)

        logger.trace(
            f"Fetched {len(all_annotations)} bbox annotation(s), "
            f"{len(all_deleted)} deleted image(s), "
            f"{len(all_without)} image(s) without annotations",
        )
        return ProjectAnnotations(
            annotations=all_annotations,
            deleted_images=all_deleted,
            images_without_annotations=all_without,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_client_kwargs(self, cfg: CvatConfig) -> dict[str, Any]:
        """Build keyword arguments for ``make_client``.

        ``organization`` is not passed to ``make_client`` (SDK does not
        accept it).  It is set on the client instance afterwards.
        """
        kwargs: dict[str, Any] = {"host": cfg.host}
        if cfg.token:
            kwargs["access_token"] = cfg.token
        elif cfg.username and cfg.password:
            kwargs["credentials"] = (cfg.username, cfg.password)
        return kwargs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _project_annotations_to_csv_rows(
    result: ProjectAnnotations,
) -> list[dict[str, str | int | float | bool | None]]:
    """Build CSV rows with the same columns as `BBoxAnnotation`."""
    rows = [ann.to_csv_row() for ann in result.annotations]
    rows.extend(e.to_csv_row() for e in result.images_without_annotations)
    return rows


def fetch_annotations(
    project_id: int,
    cfg: CvatConfig | None = None,
    *,
    completed_only: bool = False,
) -> pd.DataFrame:
    """Fetch project annotations as a pandas DataFrame.

    Includes one row per bbox annotation and one row per image that has no
    annotations (missing bbox/annotation fields filled with None).
    For full structured output (including deleted images), use ``CvatClient``.
    """
    resolved_cfg = cfg or CvatConfig.load()
    result = CvatClient(resolved_cfg).fetch_annotations(
        project_id,
        completed_only=completed_only,
    )
    rows = _project_annotations_to_csv_rows(result)
    if not rows:
        return pd.DataFrame(columns=list(BBoxAnnotation.model_fields.keys()))
    return pd.DataFrame(rows)

"""CVAT client logic: connect, fetch annotations, extract shapes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
from cvat_sdk import make_client
from loguru import logger

from cveta2._client.context import _TaskContext
from cveta2._client.extractors import _collect_shapes, _collect_track_shapes
from cveta2._client.mapping import _build_label_maps
from cveta2.config import CvatConfig
from cveta2.models import BBoxAnnotation, DeletedImage, ProjectAnnotations

if TYPE_CHECKING:
    from collections.abc import Callable


class CvatClient:
    """High-level CVAT client that fetches bbox annotations."""

    def __init__(
        self,
        cfg: CvatConfig,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        """Store client configuration and optional SDK client factory."""
        self._cfg = cfg
        self._client_factory = client_factory or make_client

    def fetch_annotations(
        self,
        project_id: int,
        *,
        completed_only: bool = False,
    ) -> ProjectAnnotations:
        """Fetch all bounding-box annotations and deleted images from a CVAT project.

        Returns a ``ProjectAnnotations`` with one ``BBoxAnnotation`` per bounding
        box and a flat list of ``DeletedImage`` records.

        If ``completed_only`` is True, only tasks with status "completed" are processed.
        """
        resolved = self._cfg.ensure_credentials()
        client_kwargs = self._build_client_kwargs(resolved)

        with self._client_factory(**client_kwargs) as client:
            project = client.projects.retrieve(project_id)
            logger.info(f"Project: {project.name} (id={project.id})")
            logger.debug(f"Project structure from API: {project}")

            label_names, attr_names = _build_label_maps(project)

            tasks = project.get_tasks()
            logger.debug(f"Tasks structure from API: {tasks}")
            if completed_only:
                tasks = [t for t in tasks if getattr(t, "status", None) == "completed"]
                logger.info(f"Filtered to {len(tasks)} completed task(s)")
                logger.debug(f"Completed tasks structure from API: {tasks}")
            if not tasks:
                logger.warning("No tasks in this project.")
                return ProjectAnnotations(annotations=[], deleted_images=[])

            all_annotations: list[BBoxAnnotation] = []
            all_deleted: list[DeletedImage] = []

            for task in tasks:
                logger.info(f"Processing task {task.id} ({task.name})")
                logger.trace(f"Task structure from API: {task}")

                data_meta, _ = client.api_client.tasks_api.retrieve_data_meta(
                    task.id,
                )
                logger.debug(f"Task data_meta structure from API: {data_meta}")
                frames: dict[int, Any] = dict(enumerate(data_meta.frames or []))
                logger.trace(
                    f"Task frames structure from API: {data_meta.frames or []}",
                )

                # Deleted frames
                logger.trace(
                    f"Task deleted_frames structure from API: "
                    f"{data_meta.deleted_frames or []}",
                )
                for frame_id in data_meta.deleted_frames or []:
                    frame_info = frames.get(frame_id)
                    all_deleted.append(
                        DeletedImage(
                            task_id=task.id,
                            task_name=task.name,
                            frame_id=frame_id,
                            image_name=(frame_info.name if frame_info else "<unknown>"),
                        ),
                    )

                # Annotations
                labeled_data, _ = client.api_client.tasks_api.retrieve_annotations(
                    task.id,
                )
                logger.debug(
                    f"Task annotations structure from API: {labeled_data}",
                )
                task_status = str(getattr(task, "status", "") or "")
                task_updated_date_raw = getattr(task, "updated_date", None) or getattr(
                    task, "updated_at", None
                )
                if task_updated_date_raw is None:
                    task_updated_date = ""
                elif hasattr(task_updated_date_raw, "isoformat"):
                    task_updated_date = task_updated_date_raw.isoformat()
                else:
                    task_updated_date = str(task_updated_date_raw)
                ctx = _TaskContext(
                    frames=frames,
                    label_names=label_names,
                    attr_names=attr_names,
                    task_id=task.id,
                    task_name=task.name,
                    task_status=task_status,
                    task_updated_date=task_updated_date,
                    subset=task.subset or "",
                )

                all_annotations.extend(_collect_shapes(labeled_data.shapes or [], ctx))
                all_annotations.extend(
                    _collect_track_shapes(labeled_data.tracks or [], ctx),
                )

            logger.info(
                f"Fetched {len(all_annotations)} bbox annotation(s), "
                f"{len(all_deleted)} deleted image(s)",
            )
            return ProjectAnnotations(
                annotations=all_annotations,
                deleted_images=all_deleted,
            )

    def _build_client_kwargs(self, cfg: CvatConfig) -> dict[str, Any]:
        """Build keyword arguments for ``make_client`` from a resolved config."""
        kwargs: dict[str, Any] = {"host": cfg.host}
        if cfg.token:
            kwargs["access_token"] = cfg.token
        elif cfg.username and cfg.password:
            kwargs["credentials"] = (cfg.username, cfg.password)
        return kwargs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_annotations(
    project_id: int,
    cfg: CvatConfig | None = None,
    *,
    completed_only: bool = False,
) -> pd.DataFrame:
    """Fetch project annotations as a pandas DataFrame.

    This public helper intentionally returns only bbox annotations in tabular form.
    For full structured output (including deleted images), use ``CvatClient``.
    """
    resolved_cfg = cfg or CvatConfig.load()
    result = CvatClient(resolved_cfg).fetch_annotations(
        project_id,
        completed_only=completed_only,
    )
    if not result.annotations:
        return pd.DataFrame(columns=list(BBoxAnnotation.model_fields.keys()))
    return pd.DataFrame([ann.model_dump() for ann in result.annotations])

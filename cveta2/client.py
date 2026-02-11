"""CVAT client logic: connect, fetch annotations, extract shapes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger
from tqdm import tqdm

from cveta2._client.context import _TaskContext
from cveta2._client.extractors import _collect_shapes, _collect_track_shapes
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
    from cveta2._client.dtos import RawFrame, RawTask
    from cveta2._client.ports import CvatApiPort


class CvatClient:
    """High-level CVAT client that fetches bbox annotations."""

    def __init__(
        self,
        cfg: CvatConfig,
        api: CvatApiPort | None = None,
    ) -> None:
        """Store client configuration and optional API adapter.

        Parameters
        ----------
        cfg:
            CVAT connection settings.
        api:
            An object satisfying ``CvatApiPort``.  When *None* (the default),
            a ``SdkCvatApiAdapter`` backed by the real CVAT SDK is created.

        """
        self._cfg = cfg
        self._api: CvatApiPort = api or SdkCvatApiAdapter(cfg)

    def list_projects(self) -> list[ProjectInfo]:
        """Fetch list of projects from CVAT (id and name)."""
        raw = self._api.list_projects()
        return [ProjectInfo(id=p.id, name=p.name) for p in raw]

    def resolve_project_id(
        self,
        project_spec: int | str,
        *,
        cached: list[ProjectInfo] | None = None,
    ) -> int:
        """Resolve project id from numeric id or project name.

        If project_spec is int or digit string, returns it as int.
        If it is a name, looks in cached list first, then in list_projects() from API.
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
        """Fetch all bounding-box annotations and deleted images from a CVAT project.

        Returns a ``ProjectAnnotations`` with one ``BBoxAnnotation`` per bounding
        box and a flat list of ``DeletedImage`` records.

        If ``completed_only`` is True, only tasks with status "completed" are processed.
        """
        labels = self._api.get_project_labels(project_id)
        label_names, attr_names = _build_label_maps(labels)

        tasks = self._api.get_project_tasks(project_id)
        if completed_only:
            tasks = [t for t in tasks if t.status == "completed"]
            logger.trace(f"Filtered to {len(tasks)} completed task(s)")
        if not tasks:
            logger.warning("No tasks in this project.")
            return ProjectAnnotations(annotations=[], deleted_images=[])

        all_annotations: list[BBoxAnnotation] = []
        all_deleted: list[DeletedImage] = []
        all_without_annotations: list[ImageWithoutAnnotations] = []

        for task in tqdm(tasks, desc="Processing tasks", unit="task"):
            task_annotations, task_deleted, task_without_annotations = (
                self._process_task(
                    task=task,
                    label_names=label_names,
                    attr_names=attr_names,
                )
            )
            all_annotations.extend(task_annotations)
            all_deleted.extend(task_deleted)
            all_without_annotations.extend(task_without_annotations)

        logger.trace(
            f"Fetched {len(all_annotations)} bbox annotation(s), "
            f"{len(all_deleted)} deleted image(s), "
            f"{len(all_without_annotations)} image(s) without annotations",
        )
        return ProjectAnnotations(
            annotations=all_annotations,
            deleted_images=all_deleted,
            images_without_annotations=all_without_annotations,
        )

    def _process_task(
        self,
        task: RawTask,
        label_names: dict[int, str],
        attr_names: dict[int, str],
    ) -> tuple[list[BBoxAnnotation], list[DeletedImage], list[ImageWithoutAnnotations]]:
        logger.trace(f"Processing task {task.id} ({task.name})")

        data_meta = self._api.get_task_data_meta(task.id)
        frames: dict[int, RawFrame] = dict(enumerate(data_meta.frames))
        deleted_frame_ids = data_meta.deleted_frames

        annotations_data = self._api.get_task_annotations(task.id)

        ctx = _TaskContext(
            frames=frames,
            label_names=label_names,
            attr_names=attr_names,
            task_id=task.id,
            task_name=task.name,
            task_status=task.status,
            task_updated_date=task.updated_date,
            subset=task.subset,
        )
        task_annotations = _collect_shapes(annotations_data.shapes, ctx)
        task_annotations.extend(_collect_track_shapes(annotations_data.tracks, ctx))
        task_deleted = self._collect_deleted_images(
            task=task,
            frames=frames,
            deleted_frame_ids=deleted_frame_ids,
        )
        task_without_annotations = self._collect_without_annotations(
            ctx=ctx,
            frames=frames,
            deleted_frame_ids=set(deleted_frame_ids),
            annotated_frame_ids={a.frame_id for a in task_annotations},
        )
        return task_annotations, task_deleted, task_without_annotations

    @staticmethod
    def _collect_deleted_images(
        task: RawTask,
        frames: dict[int, RawFrame],
        deleted_frame_ids: list[int],
    ) -> list[DeletedImage]:
        deleted_images: list[DeletedImage] = []
        for frame_id in deleted_frame_ids:
            frame_info = frames.get(frame_id)
            image_name = frame_info.name if frame_info else "<unknown>"
            deleted_images.append(
                DeletedImage(
                    task_id=task.id,
                    task_name=task.name,
                    task_status=task.status,
                    task_updated_date=task.updated_date,
                    frame_id=frame_id,
                    image_name=image_name,
                ),
            )
        return deleted_images

    @staticmethod
    def _collect_without_annotations(
        ctx: _TaskContext,
        frames: dict[int, RawFrame],
        deleted_frame_ids: set[int],
        annotated_frame_ids: set[int],
    ) -> list[ImageWithoutAnnotations]:
        result: list[ImageWithoutAnnotations] = []
        for frame_id, frame_info in frames.items():
            if frame_id in deleted_frame_ids or frame_id in annotated_frame_ids:
                continue
            result.append(
                ImageWithoutAnnotations(
                    image_name=frame_info.name,
                    image_width=frame_info.width,
                    image_height=frame_info.height,
                    task_id=ctx.task_id,
                    task_name=ctx.task_name,
                    task_status=ctx.task_status,
                    task_updated_date=ctx.task_updated_date,
                    frame_id=frame_id,
                    subset=ctx.subset,
                ),
            )
        return result


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

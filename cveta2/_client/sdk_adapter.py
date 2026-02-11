"""CVAT SDK adapter implementing ``CvatApiPort``.

This is the only module that imports and interacts with ``cvat_sdk``.
It converts opaque SDK objects into typed DTOs from ``dtos.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cvat_sdk import make_client  # type: ignore[import-untyped]
from loguru import logger

from cveta2._client.dtos import (
    RawAnnotations,
    RawAttribute,
    RawDataMeta,
    RawFrame,
    RawLabel,
    RawLabelAttribute,
    RawProject,
    RawShape,
    RawTask,
    RawTrack,
    RawTrackedShape,
)

if TYPE_CHECKING:
    from cvat_sdk.api_client import (  # type: ignore[import-untyped]
        models as cvat_models,
    )

    from cveta2.config import CvatConfig


class SdkCvatApiAdapter:
    """``CvatApiPort`` implementation backed by the real CVAT SDK."""

    def __init__(self, cfg: CvatConfig) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Public API (satisfies CvatApiPort)
    # ------------------------------------------------------------------

    def list_projects(self) -> list[RawProject]:
        """Return all accessible projects."""
        with self._open_client() as client:
            raw = client.projects.list()
            return [RawProject(id=p.id, name=p.name or "") for p in raw]

    def get_project(self, project_id: int) -> RawProject:
        """Return a single project by ID."""
        with self._open_client() as client:
            p = client.projects.retrieve(project_id)
            return RawProject(id=p.id, name=p.name or "")

    def get_project_tasks(self, project_id: int) -> list[RawTask]:
        """Return tasks belonging to a project."""
        with self._open_client() as client:
            project = client.projects.retrieve(project_id)
            logger.trace(f"Project structure from API: {project}")
            tasks = project.get_tasks()
            logger.trace(f"Tasks structure from API: {tasks}")
            return [self._convert_task(t) for t in tasks]

    def get_project_labels(self, project_id: int) -> list[RawLabel]:
        """Return label definitions for a project."""
        with self._open_client() as client:
            project = client.projects.retrieve(project_id)
            labels = project.get_labels()
            logger.trace(f"Project labels structure from API: {labels}")
            return [self._convert_label(lbl) for lbl in labels]

    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        """Return frame metadata and deleted frame IDs for a task."""
        with self._open_client() as client:
            tasks_api = client.api_client.tasks_api
            data_meta, _ = tasks_api.retrieve_data_meta(task_id)
            logger.trace(f"Task data_meta structure from API: {data_meta}")
            return self._convert_data_meta(data_meta)

    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        """Return shapes and tracks for a task."""
        with self._open_client() as client:
            tasks_api = client.api_client.tasks_api
            labeled_data, _ = tasks_api.retrieve_annotations(task_id)
            logger.trace(f"Task annotations structure from API: {labeled_data}")
            return self._convert_annotations(labeled_data)

    # ------------------------------------------------------------------
    # SDK client lifecycle
    # ------------------------------------------------------------------

    def _open_client(self) -> Any:  # noqa: ANN401
        """Create and return a context-managed SDK client."""
        resolved = self._cfg.ensure_credentials()
        kwargs: dict[str, Any] = {"host": resolved.host}
        if resolved.token:
            kwargs["access_token"] = resolved.token
        elif resolved.username and resolved.password:
            kwargs["credentials"] = (resolved.username, resolved.password)

        client = make_client(**kwargs)
        if resolved.organization:
            client.organization_slug = resolved.organization
            logger.trace(f"Using organization: {resolved.organization}")
        return client

    # ------------------------------------------------------------------
    # Conversion helpers (SDK objects → DTOs)
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_task(task: cvat_models.TaskRead) -> RawTask:
        logger.trace(f"Task structure from API: {task}")
        return RawTask(
            id=task.id,
            name=task.name or "",
            status=str(task.status or ""),
            subset=task.subset or "",
            updated_date=SdkCvatApiAdapter._extract_updated_date(task),
        )

    @staticmethod
    def _extract_updated_date(task: cvat_models.TaskRead) -> str:
        """Normalize ``updated_date`` / ``updated_at`` to an ISO string."""
        raw: object | None = getattr(task, "updated_date", None)
        if raw is None:
            raw = getattr(task, "updated_at", None)
        if raw is None:
            return ""
        isoformat = getattr(raw, "isoformat", None)
        if callable(isoformat):
            return str(isoformat())
        return str(raw)

    @staticmethod
    def _convert_label(label: cvat_models.Label) -> RawLabel:
        logger.trace(f"Label structure from API: {label}")
        raw_attrs = label.attributes or []
        attrs = [RawLabelAttribute(id=a.id, name=a.name or "") for a in raw_attrs]
        return RawLabel(id=label.id, name=label.name, attributes=attrs)

    @staticmethod
    def _convert_data_meta(data_meta: cvat_models.DataMetaRead) -> RawDataMeta:
        frames_raw = data_meta.frames or []
        logger.trace(f"Task frames structure from API: {frames_raw}")
        frames = [
            RawFrame(
                name=f.name or "",
                width=int(f.width or 0),
                height=int(f.height or 0),
            )
            for f in frames_raw
        ]
        deleted = list(data_meta.deleted_frames or [])
        logger.trace(f"Task deleted_frames structure from API: {deleted}")
        return RawDataMeta(frames=frames, deleted_frames=deleted)

    @staticmethod
    def _convert_annotations(labeled_data: cvat_models.LabeledData) -> RawAnnotations:
        raw_shapes = labeled_data.shapes or []
        raw_tracks = labeled_data.tracks or []
        return RawAnnotations(
            shapes=[SdkCvatApiAdapter._convert_shape(s) for s in raw_shapes],
            tracks=[SdkCvatApiAdapter._convert_track(t) for t in raw_tracks],
        )

    @staticmethod
    def _convert_shape(shape: cvat_models.LabeledShape) -> RawShape:
        logger.trace(f"Shape structure from API: {shape}")
        type_val = shape.type.value if shape.type else str(shape.type)
        return RawShape(
            id=shape.id or 0,
            type=type_val,
            frame=shape.frame,
            label_id=shape.label_id,
            points=list(shape.points or []),
            occluded=bool(shape.occluded),
            z_order=int(shape.z_order or 0),
            rotation=float(shape.rotation or 0.0),
            source=str(shape.source or ""),
            attributes=SdkCvatApiAdapter._convert_attributes(shape.attributes),
            created_by=SdkCvatApiAdapter._extract_creator_username(shape),
        )

    @staticmethod
    def _convert_tracked_shape(ts: cvat_models.TrackedShape) -> RawTrackedShape:
        logger.trace(f"Tracked shape structure from API: {ts}")
        type_str = ts.type.value if ts.type else str(ts.type)
        return RawTrackedShape(
            type=type_str,
            frame=ts.frame,
            points=list(ts.points or []),
            outside=bool(ts.outside),
            occluded=bool(ts.occluded),
            z_order=int(ts.z_order or 0),
            rotation=float(ts.rotation or 0.0),
            attributes=SdkCvatApiAdapter._convert_attributes(ts.attributes),
            created_by=SdkCvatApiAdapter._extract_creator_username(ts),
        )

    @staticmethod
    def _convert_track(track: cvat_models.LabeledTrack) -> RawTrack:
        logger.trace(f"Track structure from API: {track}")
        raw_shapes = track.shapes or []
        return RawTrack(
            id=track.id or 0,
            label_id=track.label_id,
            source=str(track.source or ""),
            shapes=[SdkCvatApiAdapter._convert_tracked_shape(s) for s in raw_shapes],
            created_by=SdkCvatApiAdapter._extract_creator_username(track),
        )

    @staticmethod
    def _convert_attributes(
        raw_attrs: list[cvat_models.AttributeVal] | None,
    ) -> list[RawAttribute]:
        if not raw_attrs:
            return []
        logger.trace(f"Raw attributes structure from API: {raw_attrs}")
        return [
            RawAttribute(spec_id=a.spec_id, value=str(a.value or "")) for a in raw_attrs
        ]

    @staticmethod
    def _extract_creator_username(item: object) -> str:
        """Extract creator username from a CVAT SDK entity."""
        user_obj = getattr(item, "created_by", None) or getattr(item, "owner", None)
        if user_obj is None:
            return ""
        username = getattr(user_obj, "username", None) or getattr(
            user_obj, "name", None
        )
        if username is not None:
            return str(username)
        if isinstance(user_obj, dict):
            return str(user_obj.get("username") or user_obj.get("name") or "")
        return ""

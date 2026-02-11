"""CVAT SDK adapter implementing ``CvatApiPort``.

This is the only module that imports and interacts with ``cvat_sdk``.
It converts opaque SDK objects into typed DTOs from ``dtos.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cvat_sdk import make_client
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
            return [
                RawProject(
                    id=getattr(p, "id", 0),
                    name=getattr(p, "name", "") or "",
                )
                for p in raw
            ]

    def get_project(self, project_id: int) -> RawProject:
        """Return a single project by ID."""
        with self._open_client() as client:
            p = client.projects.retrieve(project_id)
            return RawProject(
                id=getattr(p, "id", 0),
                name=getattr(p, "name", "") or "",
            )

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
    def _convert_task(task: object) -> RawTask:
        task_id: int = getattr(task, "id", 0)
        name: str = getattr(task, "name", "") or ""
        status: str = str(getattr(task, "status", "") or "")
        subset: str = str(getattr(task, "subset", "") or "")
        updated_date = SdkCvatApiAdapter._extract_updated_date(task)
        logger.trace(f"Task structure from API: {task}")
        return RawTask(
            id=task_id,
            name=name,
            status=status,
            subset=subset,
            updated_date=updated_date,
        )

    @staticmethod
    def _extract_updated_date(task: object) -> str:
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
    def _convert_label(label: object) -> RawLabel:
        label_id: int = getattr(label, "id", 0)
        name: str = getattr(label, "name", "") or ""
        raw_attrs: list[Any] = list(getattr(label, "attributes", None) or [])
        logger.trace(f"Label structure from API: {label}")
        attrs = [
            RawLabelAttribute(
                id=getattr(a, "id", 0),
                name=getattr(a, "name", "") or "",
            )
            for a in raw_attrs
        ]
        return RawLabel(id=label_id, name=name, attributes=attrs)

    @staticmethod
    def _convert_data_meta(data_meta: object) -> RawDataMeta:
        frames_raw: list[Any] = list(getattr(data_meta, "frames", None) or [])
        logger.trace(f"Task frames structure from API: {frames_raw}")
        frames = [
            RawFrame(
                name=getattr(f, "name", "") or "",
                width=int(getattr(f, "width", 0) or 0),
                height=int(getattr(f, "height", 0) or 0),
            )
            for f in frames_raw
        ]
        deleted: list[int] = list(getattr(data_meta, "deleted_frames", None) or [])
        logger.trace(f"Task deleted_frames structure from API: {deleted}")
        return RawDataMeta(frames=frames, deleted_frames=deleted)

    @staticmethod
    def _convert_annotations(labeled_data: object) -> RawAnnotations:
        raw_shapes: list[Any] = list(getattr(labeled_data, "shapes", None) or [])
        raw_tracks: list[Any] = list(getattr(labeled_data, "tracks", None) or [])
        shapes = [SdkCvatApiAdapter._convert_shape(s) for s in raw_shapes]
        tracks = [SdkCvatApiAdapter._convert_track(t) for t in raw_tracks]
        return RawAnnotations(shapes=shapes, tracks=tracks)

    @staticmethod
    def _convert_shape(shape: object) -> RawShape:
        logger.trace(f"Shape structure from API: {shape}")
        shape_type_obj = getattr(shape, "type", None)
        shape_type = getattr(shape_type_obj, "value", str(shape_type_obj))
        return RawShape(
            id=getattr(shape, "id", 0),
            type=shape_type,
            frame=getattr(shape, "frame", 0),
            label_id=getattr(shape, "label_id", 0),
            points=list(getattr(shape, "points", []) or []),
            occluded=bool(getattr(shape, "occluded", False)),
            z_order=int(getattr(shape, "z_order", 0) or 0),
            rotation=float(getattr(shape, "rotation", 0.0) or 0.0),
            source=str(getattr(shape, "source", "") or ""),
            attributes=SdkCvatApiAdapter._convert_attributes(
                getattr(shape, "attributes", None),
            ),
            created_by=SdkCvatApiAdapter._extract_creator_username(shape),
        )

    @staticmethod
    def _convert_tracked_shape(ts: object) -> RawTrackedShape:
        logger.trace(f"Tracked shape structure from API: {ts}")
        type_obj = getattr(ts, "type", None)
        type_str = getattr(type_obj, "value", str(type_obj))
        return RawTrackedShape(
            type=type_str,
            frame=getattr(ts, "frame", 0),
            points=list(getattr(ts, "points", []) or []),
            outside=bool(getattr(ts, "outside", False)),
            occluded=bool(getattr(ts, "occluded", False)),
            z_order=int(getattr(ts, "z_order", 0) or 0),
            rotation=float(getattr(ts, "rotation", 0.0) or 0.0),
            attributes=SdkCvatApiAdapter._convert_attributes(
                getattr(ts, "attributes", None),
            ),
            created_by=SdkCvatApiAdapter._extract_creator_username(ts),
        )

    @staticmethod
    def _convert_track(track: object) -> RawTrack:
        logger.trace(f"Track structure from API: {track}")
        raw_shapes: list[Any] = list(getattr(track, "shapes", None) or [])
        return RawTrack(
            id=getattr(track, "id", 0),
            label_id=getattr(track, "label_id", 0),
            source=str(getattr(track, "source", "") or ""),
            shapes=[SdkCvatApiAdapter._convert_tracked_shape(s) for s in raw_shapes],
            created_by=SdkCvatApiAdapter._extract_creator_username(track),
        )

    @staticmethod
    def _convert_attributes(raw_attrs: Any) -> list[RawAttribute]:  # noqa: ANN401
        if not raw_attrs:
            return []
        attrs: list[Any] = list(raw_attrs)
        logger.trace(f"Raw attributes structure from API: {attrs}")
        return [
            RawAttribute(
                spec_id=getattr(a, "spec_id", 0),
                value=str(getattr(a, "value", "") or ""),
            )
            for a in attrs
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

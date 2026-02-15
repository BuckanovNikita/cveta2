"""CVAT SDK adapter implementing ``CvatApiPort``.

This is the only module that imports and interacts with ``cvat_sdk``.
It converts opaque SDK objects into typed DTOs from ``dtos.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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


def _log_retry(retry_state: Any) -> None:  # noqa: ANN401
    """Log a warning before each retry attempt."""
    logger.warning(
        f"CVAT API call failed (attempt {retry_state.attempt_number}), "
        f"retrying: {retry_state.outcome.exception()!r}"
    )


# Retry on network / server errors with exponential backoff.
_api_retry = retry(
    retry=retry_if_exception_type((OSError, ConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    before_sleep=_log_retry,
    reraise=True,
)


class SdkCvatApiAdapter:
    """``CvatApiPort`` implementation backed by an open CVAT SDK client.

    The caller is responsible for opening and closing the SDK client.
    This adapter is a thin stateless converter: SDK objects in, DTOs out.
    All public methods are wrapped with retry logic for transient errors.
    """

    def __init__(self, client: Any) -> None:  # noqa: ANN401
        """Wrap an already-opened ``cvat_sdk`` client."""
        self._client = client

    # ------------------------------------------------------------------
    # Public API (satisfies CvatApiPort)
    # ------------------------------------------------------------------

    @_api_retry
    def list_projects(self) -> list[RawProject]:
        """Return all accessible projects."""
        raw = self._client.projects.list()
        return [RawProject(id=p.id, name=p.name or "") for p in raw]

    @_api_retry
    def get_project_tasks(self, project_id: int) -> list[RawTask]:
        """Return tasks belonging to a project."""
        project = self._client.projects.retrieve(project_id)
        tasks = project.get_tasks()
        return [self._convert_task(t) for t in tasks]

    @_api_retry
    def get_project_labels(self, project_id: int) -> list[RawLabel]:
        """Return label definitions for a project."""
        project = self._client.projects.retrieve(project_id)
        labels = project.get_labels()
        return [self._convert_label(lbl) for lbl in labels]

    @_api_retry
    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        """Return frame metadata and deleted frame IDs for a task."""
        tasks_api = self._client.api_client.tasks_api
        data_meta, _ = tasks_api.retrieve_data_meta(task_id)
        return self._convert_data_meta(data_meta)

    @_api_retry
    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        """Return shapes and tracks for a task."""
        tasks_api = self._client.api_client.tasks_api
        labeled_data, _ = tasks_api.retrieve_annotations(task_id)
        return self._convert_annotations(labeled_data)

    # ------------------------------------------------------------------
    # Conversion helpers (SDK objects -> DTOs)
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_task(task: cvat_models.TaskRead) -> RawTask:
        return RawTask(
            id=task.id,
            name=task.name or "",
            status=str(task.status or ""),
            subset=task.subset or "",
            updated_date=SdkCvatApiAdapter._extract_updated_date(task),
        )

    @staticmethod
    def _extract_updated_date(task: cvat_models.TaskRead) -> str:
        """Normalize ``updated_date`` / ``updated_at`` to ISO string.

        Uses ``getattr`` because the CVAT SDK renamed ``updated_date`` to
        ``updated_at`` between versions, and the returned value may be a
        ``datetime`` (with ``.isoformat()``) or a plain string depending on
        the SDK release.  This is an intentional exception to the project
        style rule "avoid getattr" (see CLAUDE.md).
        """
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
        raw_attrs = label.attributes or []
        attrs = [RawLabelAttribute(id=a.id, name=a.name or "") for a in raw_attrs]
        return RawLabel(id=label.id, name=label.name, attributes=attrs)

    @staticmethod
    def _convert_data_meta(
        data_meta: cvat_models.DataMetaRead,
    ) -> RawDataMeta:
        frames_raw = data_meta.frames or []
        frames = [
            RawFrame(
                name=f.name or "",
                width=int(f.width or 0),
                height=int(f.height or 0),
            )
            for f in frames_raw
        ]
        deleted = list(data_meta.deleted_frames or [])
        return RawDataMeta(frames=frames, deleted_frames=deleted)

    @staticmethod
    def _convert_annotations(
        labeled_data: cvat_models.LabeledData,
    ) -> RawAnnotations:
        raw_shapes = labeled_data.shapes or []
        raw_tracks = labeled_data.tracks or []
        return RawAnnotations(
            shapes=[SdkCvatApiAdapter._convert_shape(s) for s in raw_shapes],
            tracks=[SdkCvatApiAdapter._convert_track(t) for t in raw_tracks],
        )

    @staticmethod
    def _convert_shape(
        shape: cvat_models.LabeledShape,
    ) -> RawShape:
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
            attributes=SdkCvatApiAdapter._convert_attributes(
                shape.attributes,
            ),
            created_by=SdkCvatApiAdapter._extract_creator_username(
                shape,
            ),
        )

    @staticmethod
    def _convert_tracked_shape(
        ts: cvat_models.TrackedShape,
    ) -> RawTrackedShape:
        type_str = ts.type.value if ts.type else str(ts.type)
        return RawTrackedShape(
            type=type_str,
            frame=ts.frame,
            points=list(ts.points or []),
            outside=bool(ts.outside),
            occluded=bool(ts.occluded),
            z_order=int(ts.z_order or 0),
            rotation=float(ts.rotation or 0.0),
            attributes=SdkCvatApiAdapter._convert_attributes(
                ts.attributes,
            ),
            created_by=SdkCvatApiAdapter._extract_creator_username(
                ts,
            ),
        )

    @staticmethod
    def _convert_track(
        track: cvat_models.LabeledTrack,
    ) -> RawTrack:
        raw_shapes = track.shapes or []
        return RawTrack(
            id=track.id or 0,
            label_id=track.label_id,
            source=str(track.source or ""),
            shapes=[SdkCvatApiAdapter._convert_tracked_shape(s) for s in raw_shapes],
            created_by=SdkCvatApiAdapter._extract_creator_username(
                track,
            ),
        )

    @staticmethod
    def _convert_attributes(
        raw_attrs: list[cvat_models.AttributeVal] | None,
    ) -> list[RawAttribute]:
        if not raw_attrs:
            return []
        return [
            RawAttribute(spec_id=a.spec_id, value=str(a.value or "")) for a in raw_attrs
        ]

    @staticmethod
    def _extract_creator_username(item: object) -> str:
        """Extract creator username from a CVAT SDK entity.

        Uses ``getattr`` because the CVAT SDK represents the creator
        inconsistently across entity types and versions: ``created_by`` may
        be a user object, a dict, or absent (in which case ``owner`` is
        used).  The user object itself may expose ``username`` or ``name``.
        This is an intentional exception to the project style rule
        "avoid getattr" (see CLAUDE.md).
        """
        user_obj = getattr(item, "created_by", None) or getattr(
            item,
            "owner",
            None,
        )
        if user_obj is None:
            return ""
        username = getattr(user_obj, "username", None) or getattr(
            user_obj,
            "name",
            None,
        )
        if username is not None:
            return str(username)
        if isinstance(user_obj, dict):
            return str(
                user_obj.get("username") or user_obj.get("name") or "",
            )
        return ""

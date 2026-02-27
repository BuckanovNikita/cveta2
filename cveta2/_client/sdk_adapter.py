"""CVAT SDK adapter implementing ``CvatApiPort``.

This is the only module that imports and interacts with ``cvat_sdk``.
It converts opaque SDK objects into typed DTOs from ``dtos.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger
from tenacity import (
    RetryCallState,
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
    RawShape,
)
from cveta2.models import LabelAttributeInfo, LabelInfo, ProjectInfo, TaskInfo

if TYPE_CHECKING:
    from cvat_sdk.api_client import models as cvat_models

from cvat_sdk.api_client.exceptions import ApiTypeError


def _log_retry(retry_state: RetryCallState) -> None:
    """Log a warning before each retry attempt."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        f"CVAT API call failed (attempt {retry_state.attempt_number}), "
        f"retrying: {exc!r}"
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
        self.client = client

    # ------------------------------------------------------------------
    # Public API (satisfies CvatApiPort)
    # ------------------------------------------------------------------

    @_api_retry
    def list_projects(self) -> list[ProjectInfo]:
        """Return all accessible projects."""
        raw = self.client.projects.list()
        return [ProjectInfo(id=p.id, name=p.name or "") for p in raw]

    @_api_retry
    def get_project_tasks(self, project_id: int) -> list[TaskInfo]:
        """Return tasks belonging to a project."""
        project = self.client.projects.retrieve(project_id)
        tasks = project.get_tasks()
        return [self._convert_task(t) for t in tasks]

    @_api_retry
    def get_project_labels(self, project_id: int) -> list[LabelInfo]:
        """Return label definitions for a project."""
        project = self.client.projects.retrieve(project_id)
        labels = project.get_labels()
        return [self._convert_label(lbl) for lbl in labels]

    @_api_retry
    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        """Return frame metadata and deleted frame IDs for a task."""
        tasks_api = self.client.api_client.tasks_api
        try:
            data_meta, _ = tasks_api.retrieve_data_meta(task_id)
            return self._convert_data_meta(data_meta)
        except ApiTypeError as e:
            if "chunks_updated_date" not in str(e):
                raise
            # CVAT SDK ≤2.7 expects `chunks_updated_date` to be a datetime,
            # but CVAT server can return null for it, causing ApiTypeError
            # during deserialization.  Work around by re-fetching the raw JSON
            # and building RawDataMeta manually (skipping SDK parsing).
            _, response = tasks_api.retrieve_data_meta(task_id, _parse_response=False)
            body = (
                response.read()
                if hasattr(response, "read")
                else getattr(response, "data", b"")
            )
            data = json.loads(body.decode("utf-8"))
            return self._data_meta_from_dict(data)

    @_api_retry
    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        """Return shapes for a task."""
        tasks_api = self.client.api_client.tasks_api
        labeled_data, _ = tasks_api.retrieve_annotations(task_id)
        return self._convert_annotations(labeled_data)

    # ------------------------------------------------------------------
    # Conversion helpers (SDK objects -> DTOs)
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_task(task: cvat_models.TaskRead) -> TaskInfo:
        return TaskInfo(
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
    def _convert_label(label: cvat_models.Label) -> LabelInfo:
        raw_attrs = label.attributes or []
        attrs = [LabelAttributeInfo(id=a.id, name=a.name or "") for a in raw_attrs]
        return LabelInfo(
            id=label.id, name=label.name, attributes=attrs, color=label.color or ""
        )

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
    def _data_meta_from_dict(data: dict[str, Any]) -> RawDataMeta:
        """Build RawDataMeta from API response dict when SDK deserialization fails."""
        frames_raw = data.get("frames") or []
        frames = [
            RawFrame(
                name=f.get("name") or "",
                width=int(f.get("width") or 0),
                height=int(f.get("height") or 0),
            )
            for f in frames_raw
        ]
        deleted = list(data.get("deleted_frames") or [])
        return RawDataMeta(frames=frames, deleted_frames=deleted)

    @staticmethod
    def _convert_annotations(
        labeled_data: cvat_models.LabeledData,
    ) -> RawAnnotations:
        raw_shapes = labeled_data.shapes or []
        return RawAnnotations(
            shapes=[SdkCvatApiAdapter._convert_shape(s) for s in raw_shapes],
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

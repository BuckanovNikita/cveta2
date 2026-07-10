"""Per-task cache of CVAT metadata reused across write operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cveta2._client.assembly import build_name_to_frame

if TYPE_CHECKING:
    from cveta2._client.dtos import RawDataMeta, RawJob
    from cveta2._client.ports import CvatApiPort
    from cveta2.models import LabelInfo


@dataclass
class TaskWriteSession:
    """Lazily cached task metadata shared by consecutive write operations.

    Each property hits CVAT once and reuses the result, so an upload
    chain (annotations → issues → deleted frames) fetches ``data_meta``
    a single time.  Valid only while the task's frame set is unchanged:
    shape and issue writes are fine, recreate the session after frame
    edits.
    """

    api: CvatApiPort
    task_id: int
    _data_meta: RawDataMeta | None = field(default=None, repr=False)
    _name_to_frame: dict[str, int] | None = field(default=None, repr=False)
    _labels: list[LabelInfo] | None = field(default=None, repr=False)
    _jobs: list[RawJob] | None = field(default=None, repr=False)

    @property
    def data_meta(self) -> RawDataMeta:
        """Frame metadata and deleted frame IDs (fetched once)."""
        if self._data_meta is None:
            self._data_meta = self.api.get_task_data_meta(self.task_id)
        return self._data_meta

    @property
    def name_to_frame(self) -> dict[str, int]:
        """Image name → frame index mapping derived from ``data_meta``."""
        if self._name_to_frame is None:
            self._name_to_frame = build_name_to_frame(self.data_meta)
        return self._name_to_frame

    @property
    def labels(self) -> list[LabelInfo]:
        """Task label definitions (fetched once)."""
        if self._labels is None:
            self._labels = self.api.get_task_labels(self.task_id)
        return self._labels

    @property
    def jobs(self) -> list[RawJob]:
        """Task jobs (fetched once)."""
        if self._jobs is None:
            self._jobs = self.api.get_task_jobs(self.task_id)
        return self._jobs

"""Per-task maintenance: frame deletion, label drops, deletion, job status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from cveta2._client_ops.base import _ClientBase

if TYPE_CHECKING:
    from collections.abc import Iterable

    from cveta2._client.dtos import RawDataMeta, RawShape
    from cveta2._client.ports import CvatApiPort
    from cveta2._client_ops.session import TaskWriteSession


class _TaskOpsMixin(_ClientBase):
    """Mark frames deleted, drop labels, delete tasks and set job status."""

    def mark_frames_deleted(
        self,
        task_id: int,
        image_names: set[str],
        *,
        session: TaskWriteSession | None = None,
    ) -> int:
        """Mark frames as deleted in an existing CVAT task.

        Reads ``data_meta`` to map image names to frame indices, then
        updates the task's ``deleted_frames`` list.

        Parameters
        ----------
        task_id:
            CVAT task ID.
        image_names:
            Image file names to mark as deleted.
        session:
            Optional pre-populated :class:`TaskWriteSession` to reuse
            already-fetched task metadata.

        Returns
        -------
        int
            Number of frames actually marked as deleted.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        api = self._require_api("mark_frames_deleted")
        session = session or self.open_task_session(task_id)

        name_to_frame = session.name_to_frame
        frame_ids = sorted(name_to_frame[n] for n in image_names if n in name_to_frame)
        return self._patch_deleted_frames(api, task_id, session.data_meta, frame_ids)

    def mark_frames_deleted_by_ids(
        self,
        task_id: int,
        frame_ids: Iterable[int],
    ) -> int:
        """Mark frames as deleted in an existing CVAT task by frame IDs.

        Frame IDs outside the task's frame range are skipped with a
        warning.  The remaining IDs are merged with the current
        ``deleted_frames``.

        Parameters
        ----------
        task_id:
            CVAT task ID.
        frame_ids:
            Frame indices to mark as deleted.

        Returns
        -------
        int
            Number of frames actually marked as deleted.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        api = self._require_api("mark_frames_deleted_by_ids")

        raw_meta = api.get_task_data_meta(task_id)
        num_frames = len(raw_meta.frames)
        requested = sorted(set(frame_ids))
        valid = [fid for fid in requested if 0 <= fid < num_frames]
        unknown = [fid for fid in requested if fid < 0 or fid >= num_frames]
        if unknown:
            logger.warning(
                f"Задача {task_id}: кадры {unknown} не найдены "
                f"(в задаче {num_frames} кадров) — пропускаем"
            )
        return self._patch_deleted_frames(api, task_id, raw_meta, valid)

    @staticmethod
    def _patch_deleted_frames(
        api: CvatApiPort,
        task_id: int,
        raw_meta: RawDataMeta,
        frame_ids: list[int],
    ) -> int:
        """Union *frame_ids* with the task's deleted frames and PATCH data_meta."""
        if not frame_ids:
            return 0
        new_deleted = sorted(set(raw_meta.deleted_frames) | set(frame_ids))
        api.set_deleted_frames(task_id, new_deleted)
        logger.info(f"Помечено удалёнными {len(frame_ids)} кадров в задаче {task_id}")
        return len(frame_ids)

    def count_task_label_shapes(self, task_id: int, label: str) -> int:
        """Count annotation shapes with the given label name in a task.

        Raises ``ValueError`` (listing available labels) when the label
        does not exist in the task.

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        api = self._require_api("count_task_label_shapes")
        return len(self._find_label_shapes(api, task_id, label))

    def drop_label_annotations(self, task_id: int, label: str) -> int:
        """Delete all annotation shapes with the given label from a task.

        Resolves the label name to its ID via the task's labels, collects
        matching shapes and deletes them.

        Parameters
        ----------
        task_id:
            CVAT task ID.
        label:
            Label name whose shapes should be deleted.

        Returns
        -------
        int
            Number of shapes deleted.

        Raises
        ------
        ValueError
            When the label does not exist in the task (message lists
            available labels).

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        api = self._require_api("drop_label_annotations")
        shapes = self._find_label_shapes(api, task_id, label)
        if not shapes:
            logger.info(f"В задаче {task_id} нет аннотаций с меткой {label!r}")
            return 0
        api.delete_shapes(task_id, shapes)
        logger.info(
            f"Удалено {len(shapes)} аннотаций с меткой {label!r} из задачи {task_id}"
        )
        return len(shapes)

    @staticmethod
    def _find_label_shapes(
        api: CvatApiPort,
        task_id: int,
        label: str,
    ) -> list[RawShape]:
        """Return task shapes whose label name equals *label*.

        Raises ``ValueError`` listing available labels when no task label
        matches *label*.
        """
        task_labels = api.get_task_labels(task_id)
        label_ids = {lbl.id for lbl in task_labels if lbl.name == label}
        if not label_ids:
            available = ", ".join(sorted(str(lbl.name) for lbl in task_labels))
            raise ValueError(
                f"Метка {label!r} не найдена в задаче {task_id}. "
                f"Доступные метки: {available}"
            )
        annotations = api.get_task_annotations(task_id)
        return [s for s in annotations.shapes if s.label_id in label_ids]

    def delete_task(self, task_id: int) -> None:
        """Delete a CVAT task permanently (including its data and jobs).

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        api = self._require_api("delete_task")
        api.delete_task(task_id)
        logger.info(f"Задача {task_id} удалена")

    def set_task_jobs_status(
        self,
        task_id: int,
        *,
        stage: str | None = None,
        state: str | None = None,
    ) -> int:
        """Set stage and/or state on every job of a task.

        Only the provided fields are patched.  CVAT derives the task
        status from its jobs.

        Parameters
        ----------
        task_id:
            CVAT task ID.
        stage:
            Job stage: ``annotation``, ``validation`` or ``acceptance``.
        state:
            Job state: ``new``, ``in progress``, ``completed`` or
            ``rejected``.

        Returns
        -------
        int
            Number of jobs updated.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        if stage is None and state is None:
            raise ValueError("Укажите stage и/или state.")
        api = self._require_api("set_task_jobs_status")

        jobs = api.get_task_jobs(task_id)
        for job in jobs:
            api.update_job(job.id, stage=stage, state=state)
        logger.info(
            f"Задача {task_id}: обновлено {len(jobs)} job(s) "
            f"(stage={stage or '-'}, state={state or '-'})"
        )
        return len(jobs)

    def complete_task(self, task_id: int) -> int:
        """Mark all jobs of a task as completed.

        Sets each job's ``stage`` to ``acceptance`` and ``state`` to
        ``completed``.  CVAT derives the task status from its jobs, so
        once every job is completed the task status becomes ``completed``.

        Returns the number of jobs updated.  Requires an active context
        manager (``with CvatClient(...) as c:``).
        """
        return self.set_task_jobs_status(task_id, stage="acceptance", state="completed")

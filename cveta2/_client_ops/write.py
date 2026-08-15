"""Write operations: labels, task creation, annotation and issue upload."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2._client.assembly import (
    BBOX_COLUMNS,
    build_task_issues,
    build_upload_shapes,
)
from cveta2._client.dtos import LabelPatch, UploadTaskSpec
from cveta2._client_ops.base import _ClientBase

if TYPE_CHECKING:
    from cveta2._client_ops.session import TaskWriteSession

# Both columns must exist for a row to become an issue, and both are
# normalized the same way, so one constant drives the guard and the loop.
_ISSUE_COLUMNS = frozenset({"issue_state", "issue_text"})

_SKIP_UNKNOWN_IMAGES = "изображения не найдены"
_SKIP_MISSING_BBOX = "у строк нет полного bbox"
_SKIP_UNMAPPED_FRAMES = "не найден job для кадров изображений"


def _select_new_issue_rows(annotations_df: pd.DataFrame) -> pd.DataFrame:
    """Return deduplicated rows with ``issue_state == "new"`` and non-empty text.

    Issues are attached per-bbox, so the dedup key includes the bbox
    coordinates: distinct boxes on one image with the same text each keep
    their row; only fully identical duplicates collapse.
    """
    if not _ISSUE_COLUMNS.issubset(annotations_df.columns):
        return pd.DataFrame()
    df = annotations_df.copy()
    for column in _ISSUE_COLUMNS:
        df[column] = df[column].fillna("").astype(str).str.strip()
    new_rows: pd.DataFrame = df[(df["issue_state"] == "new") & (df["issue_text"] != "")]
    dedup_key = ["image_name", "issue_text"] + [
        col for col in BBOX_COLUMNS if col in new_rows.columns
    ]
    deduped: pd.DataFrame = new_rows.drop_duplicates(subset=dedup_key)
    return deduped


class _WriteMixin(_ClientBase):
    """Mutating CVAT operations: labels, tasks, annotations and issues."""

    def update_project_labels(
        self,
        project_id: int,
        *,
        add: list[str] | None = None,
        rename: dict[int, str] | None = None,
        delete: list[int] | None = None,
        recolor: dict[int, str] | None = None,
    ) -> None:
        """Update project labels via CVAT PATCH API.

        Parameters
        ----------
        project_id:
            CVAT project ID.
        add:
            Label names to create (CVAT assigns IDs and colors).
        rename:
            Mapping ``{label_id: new_name}`` for labels to rename.
        delete:
            Label IDs to delete.  **Destroys all annotations using
            those labels permanently.**
        recolor:
            Mapping ``{label_id: new_hex_color}`` for labels to
            change color (e.g. ``"#ff0000"``).

        Requires an active context manager.

        """
        api = self._require_api("update_project_labels")

        patches: list[LabelPatch] = [LabelPatch(name=name) for name in (add or [])]
        patches.extend(
            LabelPatch(id=lid, name=new_name)
            for lid, new_name in (rename or {}).items()
        )
        patches.extend(LabelPatch(id=lid, deleted=True) for lid in (delete or []))
        patches.extend(
            LabelPatch(id=lid, color=color) for lid, color in (recolor or {}).items()
        )
        if not patches:
            return
        api.patch_project_labels(project_id, patches)

    def create_upload_task(  # noqa: PLR0913, PLR0917
        self,
        project_id: int,
        name: str,
        image_names: list[str],
        cloud_storage_id: int,
        segment_size: int = 100,
        image_quality: int = 100,
    ) -> int:
        """Create a CVAT task backed by cloud storage images.

        Creates one task with ``segment_size`` controlling how many images
        go into each job (CVAT splits automatically).  After attaching data
        the method **waits** for CVAT to finish processing the cloud storage
        files so that subsequent annotation uploads land on the correct
        frames.  Raises ``RuntimeError`` immediately if processing fails
        (e.g. images not found in cloud storage).

        Parameters
        ----------
        project_id:
            CVAT project to attach the task to.
        name:
            Human-readable task name.
        image_names:
            File names inside the cloud storage to include in the task.
        cloud_storage_id:
            CVAT cloud storage ID to read images from.
        segment_size:
            Maximum frames per job (CVAT auto-creates multiple jobs).
        image_quality:
            JPEG compression quality for CVAT image chunks (0-100).

        Returns
        -------
        int
            The newly created task ID.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        api = self._require_api("create_upload_task")
        spec = UploadTaskSpec(
            project_id=project_id,
            name=name,
            server_files=image_names,
            cloud_storage_id=cloud_storage_id,
            segment_size=segment_size,
            image_quality=image_quality,
        )
        task_id = api.create_task(spec)
        api.attach_task_data(task_id, spec)
        return task_id

    def upload_task_annotations(
        self,
        task_id: int,
        annotations_df: pd.DataFrame,
        *,
        session: TaskWriteSession | None = None,
    ) -> int:
        """Upload bbox annotations from a DataFrame to an existing task.

        Frame indices are read from CVAT ``data_meta`` so the mapping is
        always correct regardless of how CVAT sorted the images.

        Parameters
        ----------
        task_id:
            CVAT task to upload annotations to.
        annotations_df:
            DataFrame with columns from ``dataset.csv`` (must include
            ``image_name``, ``instance_label``, ``bbox_x_tl``,
            ``bbox_y_tl``, ``bbox_x_br``, ``bbox_y_br``).
            Rows with NaN in ``instance_label`` are skipped.
        session:
            Optional pre-populated :class:`TaskWriteSession` to reuse
            already-fetched task metadata.

        Returns
        -------
        int
            Number of shapes uploaded.

        Requires an active context manager (``with CvatClient(...) as c:``).

        """
        api = self._require_api("upload_task_annotations")
        session = session or self.open_task_session(task_id)

        # Frame mapping comes from CVAT data_meta (authoritative source).
        name_to_frame = session.name_to_frame
        logger.debug(f"Задача {task_id}: получено {len(name_to_frame)} фреймов из CVAT")

        label_name_to_id: dict[str, int] = {lbl.name: lbl.id for lbl in session.labels}

        built = build_upload_shapes(annotations_df, name_to_frame, label_name_to_id)
        for label_name in dict.fromkeys(built.unknown_labels):
            logger.warning(
                f"Метка {label_name!r} не найдена в задаче {task_id} — пропускаем"
            )
        if built.unknown_images:
            logger.warning(
                f"{built.unknown_images} аннотаций пропущено: "
                f"изображение не найдено в задаче"
            )

        if built.shapes:
            api.put_task_shapes(task_id, built.shapes)
            logger.info(
                f"Загружено {len(built.shapes)} аннотаций "
                f"({len({shape.frame for shape in built.shapes})} изображений) "
                f"в задачу {task_id}"
            )
        else:
            logger.info(f"Нет аннотаций для загрузки в задачу {task_id}")

        return len(built.shapes)

    def create_task_issues(
        self,
        task_id: int,
        annotations_df: pd.DataFrame,
        *,
        session: TaskWriteSession | None = None,
    ) -> int:
        """Create open CVAT issues from rows with ``issue_state == "new"``.

        Rows whose ``issue_state`` is ``"new"`` and whose ``issue_text`` is
        non-empty become CVAT issues on *task_id*; ``issue_text`` is posted
        as the first comment.  Each bbox gets its own issue; duplicate
        ``(image_name, issue_text, bbox)`` rows are created once.  Issues
        are attached to the row's bbox; rows without a complete bbox are
        skipped with a warning.

        Returns the number of issues created.  Requires an active context
        manager (``with CvatClient(...) as c:``).
        """
        api = self._require_api("create_task_issues")
        session = session or self.open_task_session(task_id)

        new_rows = _select_new_issue_rows(annotations_df)
        if new_rows.empty:
            return 0

        built = build_task_issues(new_rows, session.name_to_frame, session.jobs)
        for issue in built.issues:
            api.create_issue(issue)

        skipped = (
            (_SKIP_UNKNOWN_IMAGES, built.unknown_images),
            (_SKIP_MISSING_BBOX, built.missing_bbox),
            (_SKIP_UNMAPPED_FRAMES, built.unmapped_frames),
        )
        for reason, names in skipped:
            if names:
                logger.warning(
                    f"Issues пропущены: {reason} в задаче {task_id}: {names}"
                )
        logger.info(f"Создано issues: {len(built.issues)} в задаче {task_id}")
        return len(built.issues)

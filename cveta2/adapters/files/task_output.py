"""Task-level fetch outputs and upload lookup using the dataset adapter."""

import shutil
from pathlib import Path

import pandas as pd
from loguru import logger

from cveta2.adapters.files.dataset import LocalDatasetFiles
from cveta2.adapters.files.image_search import resolve_images
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import TaskAnnotations, TaskInfo
from cveta2.domain.output import CSV_READ_OPTIONS, CSV_WRITE_OPTIONS, format_counts


class LocalWorkflowFiles(LocalDatasetFiles):
    """Implement task output and image lookup filesystem effects."""

    resolve_images = staticmethod(resolve_images)

    def prepare_tasks(self, output_dir: Path) -> Path:
        """Create and return the task CSV output directory."""
        tasks_dir = output_dir / ".tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        return tasks_dir

    def cleanup_tasks(self, tasks_dir: Path) -> None:
        """Remove temporary task CSV outputs with best-effort cleanup."""
        shutil.rmtree(tasks_dir, ignore_errors=True)

    def write_task_csv(
        self, task: TaskInfo, result: TaskAnnotations, tasks_dir: Path
    ) -> None:
        """Write one nonempty task annotation CSV."""
        rows = result.to_csv_rows()
        if not rows:
            return
        task_csv = tasks_dir / f"task_{task.id}.csv"
        task_df = pd.DataFrame(rows)
        task_df.to_csv(task_csv, **CSV_WRITE_OPTIONS)
        logger.trace(
            f"Task {task.name!r} (id={task.id}): {format_counts(task_df)} → {task_csv}"
        )

    def read_exclude_names(self, in_progress_path: str | None) -> set[str]:
        """Read excluded frame names from the optional CSV."""
        if not in_progress_path:
            return set()
        ip_path = Path(in_progress_path)
        if not ip_path.is_file():
            raise Cveta2Error(f"Ошибка: файл не найден: {ip_path}")
        ip_df = pd.read_csv(ip_path, **CSV_READ_OPTIONS)
        if "image_name" not in ip_df.columns:
            return set()
        names: set[str] = set(ip_df["image_name"].dropna().unique())
        logger.info(
            f"Исключено {len(names)} изображений "
            f"({len(ip_df)} строк) из in_progress.csv"
        )
        return names

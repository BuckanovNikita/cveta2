"""Public CVAT API with lazy exports for infrastructure-free inner imports."""

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "CSV_COLUMNS",
    "JOB_STAGES",
    "JOB_STATES",
    "AnnotationRecord",
    "BBoxAnnotation",
    "Connection",
    "CvatApiError",
    "CvatApiPort",
    "CvatClient",
    "CvatConfig",
    "Cveta2Error",
    "DeletedImage",
    "FetchContext",
    "IgnoredTask",
    "ImageWithoutAnnotations",
    "InteractiveModeRequiredError",
    "JobStage",
    "JobState",
    "LabelAttributeInfo",
    "LabelInfo",
    "LabelsMismatchError",
    "MissingCredentialsError",
    "MissingHostError",
    "PartitionResult",
    "ProjectAnnotations",
    "ProjectInfo",
    "ProjectNotFoundError",
    "Split",
    "TaskAnnotations",
    "TaskInfo",
    "TaskNotFoundError",
    "UploadResult",
    "WhatsNewResult",
    "convert_from_yolo",
    "convert_to_coco",
    "convert_to_yolo",
    "fetch",
    "fetch_task",
    "get_labels",
    "ignore",
    "merge",
    "partition_annotations_df",
    "s3_sync",
    "task_delete",
    "task_drop_label",
    "task_mark_deleted",
    "task_set_status",
    "update_labels",
    "upload",
    "whats_new",
]

_EXPORTS = {
    "CvatApiPort": ("cveta2.application.ports.cvat", "CvatApiPort"),
    "Connection": ("cveta2.api", "Connection"),
    "UploadResult": ("cveta2.api", "UploadResult"),
    "WhatsNewResult": ("cveta2.api", "WhatsNewResult"),
    "convert_from_yolo": ("cveta2.api", "convert_from_yolo"),
    "convert_to_coco": ("cveta2.api", "convert_to_coco"),
    "convert_to_yolo": ("cveta2.api", "convert_to_yolo"),
    "fetch": ("cveta2.api", "fetch"),
    "fetch_task": ("cveta2.api", "fetch_task"),
    "get_labels": ("cveta2.api", "get_labels"),
    "ignore": ("cveta2.api", "ignore"),
    "merge": ("cveta2.api", "merge"),
    "s3_sync": ("cveta2.api", "s3_sync"),
    "task_delete": ("cveta2.api", "task_delete"),
    "task_drop_label": ("cveta2.api", "task_drop_label"),
    "task_mark_deleted": ("cveta2.api", "task_mark_deleted"),
    "task_set_status": ("cveta2.api", "task_set_status"),
    "update_labels": ("cveta2.api", "update_labels"),
    "upload": ("cveta2.api", "upload"),
    "whats_new": ("cveta2.api", "whats_new"),
    "CvatClient": ("cveta2.client", "CvatClient"),
    "FetchContext": ("cveta2.client", "FetchContext"),
    "CvatConfig": ("cveta2.config", "CvatConfig"),
    "IgnoredTask": ("cveta2.config", "IgnoredTask"),
    "PartitionResult": ("cveta2.dataset_partition", "PartitionResult"),
    "partition_annotations_df": (
        "cveta2.dataset_partition",
        "partition_annotations_df",
    ),
    "CvatApiError": ("cveta2.exceptions", "CvatApiError"),
    "Cveta2Error": ("cveta2.exceptions", "Cveta2Error"),
    "InteractiveModeRequiredError": (
        "cveta2.exceptions",
        "InteractiveModeRequiredError",
    ),
    "LabelsMismatchError": ("cveta2.exceptions", "LabelsMismatchError"),
    "MissingCredentialsError": ("cveta2.exceptions", "MissingCredentialsError"),
    "MissingHostError": ("cveta2.exceptions", "MissingHostError"),
    "ProjectNotFoundError": ("cveta2.exceptions", "ProjectNotFoundError"),
    "TaskNotFoundError": ("cveta2.exceptions", "TaskNotFoundError"),
    "CSV_COLUMNS": ("cveta2.models", "CSV_COLUMNS"),
    "JOB_STAGES": ("cveta2.models", "JOB_STAGES"),
    "JOB_STATES": ("cveta2.models", "JOB_STATES"),
    "AnnotationRecord": ("cveta2.models", "AnnotationRecord"),
    "BBoxAnnotation": ("cveta2.models", "BBoxAnnotation"),
    "DeletedImage": ("cveta2.models", "DeletedImage"),
    "ImageWithoutAnnotations": ("cveta2.models", "ImageWithoutAnnotations"),
    "JobStage": ("cveta2.models", "JobStage"),
    "JobState": ("cveta2.models", "JobState"),
    "LabelAttributeInfo": ("cveta2.models", "LabelAttributeInfo"),
    "LabelInfo": ("cveta2.models", "LabelInfo"),
    "ProjectAnnotations": ("cveta2.models", "ProjectAnnotations"),
    "ProjectInfo": ("cveta2.models", "ProjectInfo"),
    "Split": ("cveta2.models", "Split"),
    "TaskAnnotations": ("cveta2.models", "TaskAnnotations"),
    "TaskInfo": ("cveta2.models", "TaskInfo"),
}


def __dir__() -> list[str]:
    """Expose supported names to introspection without loading their modules."""
    return sorted(set(globals()) | set(__all__))


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attribute = _EXPORTS[name]
    # Resolve the fixed export table lazily without importing SDKs for inner users.
    value: object = getattr(import_module(module), attribute)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from cveta2.api import (
        Connection,
        UploadResult,
        WhatsNewResult,
        convert_from_yolo,
        convert_to_coco,
        convert_to_yolo,
        fetch,
        fetch_task,
        get_labels,
        ignore,
        merge,
        s3_sync,
        task_delete,
        task_drop_label,
        task_mark_deleted,
        task_set_status,
        update_labels,
        upload,
        whats_new,
    )
    from cveta2.application.ports.cvat import CvatApiPort
    from cveta2.client import CvatClient, FetchContext
    from cveta2.config import CvatConfig, IgnoredTask
    from cveta2.dataset_partition import PartitionResult, partition_annotations_df
    from cveta2.exceptions import (
        CvatApiError,
        Cveta2Error,
        InteractiveModeRequiredError,
        LabelsMismatchError,
        MissingCredentialsError,
        MissingHostError,
        ProjectNotFoundError,
        TaskNotFoundError,
    )
    from cveta2.models import (
        CSV_COLUMNS,
        JOB_STAGES,
        JOB_STATES,
        AnnotationRecord,
        BBoxAnnotation,
        DeletedImage,
        ImageWithoutAnnotations,
        JobStage,
        JobState,
        LabelAttributeInfo,
        LabelInfo,
        ProjectAnnotations,
        ProjectInfo,
        Split,
        TaskAnnotations,
        TaskInfo,
    )

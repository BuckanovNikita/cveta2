"""cveta2 -- CVAT project annotation utilities.

Workflow functions mirror the data CLI commands::

    import cveta2

    result = cveta2.fetch("my-project", output_dir="out")
    print(result.dataset)  # + .obsolete / .in_progress / .deleted_images
    cveta2.upload("out/dataset.csv", "my-project", "task-1")
    cveta2.convert_to_yolo("out/dataset.csv", "yolo_out/")
"""

from cveta2._client.ports import CvatApiPort
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

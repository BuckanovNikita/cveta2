"""cveta2 -- CVAT project annotation utilities."""

from cveta2._client.ports import CvatApiPort
from cveta2.client import CvatClient, FetchContext, fetch_annotations
from cveta2.dataset_partition import PartitionResult, partition_annotations_df
from cveta2.exceptions import (
    Cveta2Error,
    InteractiveModeRequiredError,
    ProjectNotFoundError,
    TaskNotFoundError,
)
from cveta2.models import (
    CSV_COLUMNS,
    AnnotationRecord,
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
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
    "AnnotationRecord",
    "BBoxAnnotation",
    "CvatApiPort",
    "CvatClient",
    "Cveta2Error",
    "DeletedImage",
    "FetchContext",
    "ImageWithoutAnnotations",
    "InteractiveModeRequiredError",
    "LabelAttributeInfo",
    "LabelInfo",
    "PartitionResult",
    "ProjectAnnotations",
    "ProjectInfo",
    "ProjectNotFoundError",
    "Split",
    "TaskAnnotations",
    "TaskInfo",
    "TaskNotFoundError",
    "fetch_annotations",
    "partition_annotations_df",
]

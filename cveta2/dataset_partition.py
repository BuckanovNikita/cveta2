"""Compatible public exports from canonical implementations."""

from cveta2.domain.partition import (
    PartitionResult,
    completed_task_ids,
    partition_annotations_df,
)

__all__ = ["PartitionResult", "completed_task_ids", "partition_annotations_df"]

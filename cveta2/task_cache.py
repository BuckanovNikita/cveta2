"""Compatible public exports from canonical implementations."""

from cveta2.adapters.s3.task_cache import (
    S3CacheBackend,
    TaskAnnotationCache,
    get_task_cache_dir,
)
from cveta2.composition.workflows import (
    invalidate_local_entry,
)
from cveta2.domain.cache import (
    CACHE_SCHEMA_VERSION,
    CachedTaskEnvelope,
)

__all__ = [
    "CACHE_SCHEMA_VERSION",
    "CachedTaskEnvelope",
    "S3CacheBackend",
    "TaskAnnotationCache",
    "get_task_cache_dir",
    "invalidate_local_entry",
]

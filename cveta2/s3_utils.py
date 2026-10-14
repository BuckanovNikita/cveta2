"""Compatible public exports from canonical implementations."""

from cveta2.adapters.s3.utils import (
    S3_TRANSFER_ERRORS,
    list_s3_objects,
    make_s3_client,
    run_s3_transfers,
    s3_get_bytes,
    s3_object_exists,
    s3_retry,
    set_default_data_timeout,
)
from cveta2.domain.paths import (
    build_s3_key,
    names_with_basename_fallback,
    parse_sync_root,
    pick_latest_duplicate,
    strip_key_prefix,
)

__all__ = [
    "S3_TRANSFER_ERRORS",
    "build_s3_key",
    "list_s3_objects",
    "make_s3_client",
    "names_with_basename_fallback",
    "parse_sync_root",
    "pick_latest_duplicate",
    "run_s3_transfers",
    "s3_get_bytes",
    "s3_object_exists",
    "s3_retry",
    "set_default_data_timeout",
    "strip_key_prefix",
]

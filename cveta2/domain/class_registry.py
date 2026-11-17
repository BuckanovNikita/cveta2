"""Complete class-registry records and their order-independent identity."""

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field


class ApiClass(BaseModel):
    """The class API identity uses number, independently of its internal id."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    id: int
    number: int
    name: str = Field(min_length=1)
    techClass: bool  # noqa: N815 - external registry field.
    isPeriodical: bool  # noqa: N815 - external registry field.
    isCritical: bool  # noqa: N815 - external registry field.
    threshold: float = Field(allow_inf_nan=False)


def registry_fingerprint(records: list[ApiClass]) -> str:
    """Bind every registry field independently of response order."""
    content = [record.model_dump(mode="json") for record in sorted(records, key=lambda record: record.number)]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

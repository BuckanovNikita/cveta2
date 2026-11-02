"""Portable policy rejects ambiguous sources before any effects run."""

import pytest
from pydantic import ValidationError

from cveta2.domain.managed.models import SourceDefinition, SplitPolicy


def test_default_splits_and_invalid_distribution() -> None:
    """The approved split defaults and complete distribution are contractual."""
    assert SplitPolicy().model_dump() == {
        "train": 0.6,
        "val": 0.2,
        "test": 0.2,
        "seed": 42,
    }
    with pytest.raises(ValidationError):
        SplitPolicy(train=0.8)


@pytest.mark.parametrize(
    "uri",
    [
        "s3://bucket/folder/",
        "s3://user@bucket/data.csv",
        "s3://bucket/../a.csv",
        "https://bucket/a.csv",
    ],
)
def test_invalid_csv_source(uri: str) -> None:
    """CSV sources are exact S3 objects without credential or path ambiguity."""
    with pytest.raises(ValidationError):
        SourceDefinition(name="imported", type="s3-csv", uri=uri)


def test_source_reference_is_exclusive() -> None:
    """A source cannot imply two different acquisition paths."""
    with pytest.raises(ValidationError):
        SourceDefinition(name="main", type="cvat", project="p", uri="s3://bucket/a.csv")

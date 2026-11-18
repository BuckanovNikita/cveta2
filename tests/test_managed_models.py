"""Portable policy rejects ambiguous sources before any effects run."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from cveta2.adapters.files.managed_sources import LocalSourceFiles
from cveta2.domain.managed.evidence import require_complete_evidence
from cveta2.domain.managed.models import ManagedError, ManagedSnapshot, SourceDefinition, SourceSnapshot, SplitPolicy


@pytest.mark.parametrize("missing_labels", [True, False], ids=["missing-labels", "mismatched-labels"])
def test_s3_source_does_not_skip_validation_of_later_cvat_evidence(*, missing_labels: bool) -> None:
    snapshot = ManagedSnapshot(
        definition_hash="recorded-definition",
        registry=[],
        registry_hash="4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        sources=[
            SourceSnapshot(name="imported", type="s3-csv", uri="s3://bucket/source.csv"),
            SourceSnapshot(
                name="live",
                type="cvat",
                project_id=12,
                labels=None if missing_labels else [],
                labels_fingerprint="0" * 64,
            ),
        ],
    )

    with pytest.raises(ManagedError, match="live"):
        require_complete_evidence(snapshot)


def test_saved_unicode_full_records_keep_their_persisted_fingerprints() -> None:
    path = Path(__file__).parent / "fixtures" / "managed_full_records_v1_unicode.yaml"

    snapshot = LocalSourceFiles().read_snapshot(path)
    require_complete_evidence(snapshot)

    assert snapshot.registry is not None
    assert snapshot.registry[0].name == "Кошка"
    assert snapshot.sources[0].labels is not None
    assert snapshot.sources[0].labels[0].attributes[0].values == ["", "видно"]


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

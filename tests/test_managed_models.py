"""Portable policy rejects ambiguous sources before any effects run."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cveta2.adapters.files.managed_sources import LocalSourceFiles
from cveta2.domain.bundle.models import DatasetMetadata
from cveta2.domain.managed.evidence import require_complete_evidence
from cveta2.domain.managed.models import (
    DatasetDefinition,
    ManagedError,
    ManagedSnapshot,
    ProjectConfig,
    SourceDefinition,
    SourceSnapshot,
    dataset_definition,
    definition_fingerprint,
    source_fingerprint,
)

_SHARED: dict[str, Any] = {
    "cvat": {"host": "https://cvat.example", "organization": "team"},
    "projects": {
        "main": {"id": 12, "name": "Main", "ignore": [{"id": 5, "name": "broken", "description": "old"}, {"id": 3}]},
        "other": {"id": 27},
    },
    "datasets": {
        "combined": {
            "sources": [
                {"name": "main", "type": "cvat", "project": "main"},
                {"name": "other", "type": "cvat", "project": "other"},
                {"name": "imported", "type": "s3-csv", "uri": "s3://annotations/imported.csv"},
            ],
            "clearml": {"project": "CV/combined", "dataset": "annotations"},
            "api_url": "https://classes.example/api",
            "s3_roots": ["s3://images/a", "s3://images/b"],
            "empty_classes": [3, 1],
            "overlaps": {
                "digest": {"source": "main", "members": ["main", "imported"]},
                "another": {"source": None, "members": ["other", "main"]},
            },
        }
    },
}
type Edit = Callable[[dict[str, Any]], object]
_DATASET = ("datasets", "combined")


def _fingerprints(edit: Edit | None = None) -> tuple[str, str]:
    raw = copy.deepcopy(_SHARED)
    if edit is not None:
        edit(raw)
    config = ProjectConfig.model_validate(raw)
    definition = dataset_definition(config, "combined")
    return source_fingerprint(config, definition), definition_fingerprint(config, definition)


def _dataset(raw: dict[str, Any]) -> dict[str, Any]:
    dataset: dict[str, Any] = raw["datasets"]["combined"]
    return dataset


def _main(raw: dict[str, Any]) -> dict[str, Any]:
    project: dict[str, Any] = raw["projects"]["main"]
    return project


_NEUTRAL: dict[str, Edit] = {
    "source-order": lambda raw: _dataset(raw)["sources"].reverse(),
    "ignored-task-bookkeeping": lambda raw: _main(raw)["ignore"][0].update(
        name="renamed", description="new", silent=True
    ),
    "ignored-task-order": lambda raw: _main(raw)["ignore"].reverse(),
    "project-bookkeeping": lambda raw: _main(raw).update(
        name="Renamed", sync_root="s3://images/main", ignored_prefix="images/", task_cache_s3="s3://cache/main"
    ),
    "project-key": lambda raw: (
        raw["projects"].update(renamed=raw["projects"].pop("main")),
        _dataset(raw)["sources"][0].update(project="renamed"),
    ),
    "unrelated-project": lambda raw: raw["projects"].update(unused={"id": 99, "ignore": [{"id": 1}]}),
    "unrelated-dataset": lambda raw: raw["datasets"].update(
        unused={**copy.deepcopy(_dataset(raw)), "clearml": {"project": "CV/unused", "dataset": "annotations"}}
    ),
    "s3-root-order": lambda raw: _dataset(raw)["s3_roots"].reverse(),
    "empty-class-order": lambda raw: _dataset(raw)["empty_classes"].reverse(),
    "overlap-member-order": lambda raw: _dataset(raw)["overlaps"]["digest"]["members"].reverse(),
    "overlap-order": lambda raw: _dataset(raw).update(overlaps=dict(reversed(_dataset(raw)["overlaps"].items()))),
}
_POLICY: dict[str, Edit] = {
    "overlap-added": lambda raw: _dataset(raw)["overlaps"].update(third={"source": None, "members": ["main", "other"]}),
    "overlap-choice": lambda raw: _dataset(raw)["overlaps"]["digest"].update(source="imported"),
    "empty-classes": lambda raw: _dataset(raw)["empty_classes"].append(7),
    "s3-roots": lambda raw: _dataset(raw)["s3_roots"].append("s3://images/c"),
    "api-url": lambda raw: _dataset(raw).update(api_url="https://classes.example/v2"),
    "clearml": lambda raw: _dataset(raw).update(clearml={"project": "CV/other", "dataset": "annotations"}),
}
_SOURCE: dict[str, Edit] = {
    "host": lambda raw: raw["cvat"].update(host="https://cvat.other.example"),
    "organization": lambda raw: raw["cvat"].update(organization=None),
    "project-id": lambda raw: _main(raw).update(id=13),
    "ignored-task-id": lambda raw: _main(raw)["ignore"].append({"id": 8}),
    "source-uri": lambda raw: _dataset(raw)["sources"][2].update(uri="s3://annotations/other.csv"),
    "source-name": lambda raw: _dataset(raw)["sources"][1].update(name="renamed"),
    "source-removed": lambda raw: _dataset(raw)["sources"].pop(),
}


@pytest.mark.parametrize("edit", _NEUTRAL.values(), ids=_NEUTRAL.keys())
def test_bookkeeping_and_order_change_no_fingerprint(edit: Edit) -> None:
    assert _fingerprints(edit) == _fingerprints()


@pytest.mark.parametrize("edit", _POLICY.values(), ids=_POLICY.keys())
def test_policy_change_keeps_fetch_but_changes_definition(edit: Edit) -> None:
    source, definition = _fingerprints(edit)
    assert source == _fingerprints()[0]
    assert definition != _fingerprints()[1]


@pytest.mark.parametrize("edit", _SOURCE.values(), ids=_SOURCE.keys())
def test_source_change_changes_both_fingerprints(edit: Edit) -> None:
    source, definition = _fingerprints(edit)
    assert source != _fingerprints()[0]
    assert definition != _fingerprints()[1]


def test_unknown_dataset_is_a_managed_error() -> None:
    with pytest.raises(ManagedError, match="Unknown managed dataset"):
        dataset_definition(ProjectConfig.model_validate(_SHARED), "missing")


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


def test_published_0_15_definition_with_splits_is_read() -> None:
    raw = {
        "api_url": "https://classes.example/api",
        "classes": {"cat": {"prod_id": 7}},
        "managed": {
            "name": "combined",
            "definition_hash": "0" * 64,
            "cvat": {"host": "https://cvat.example"},
            "assignments": {"h": "test"},
            "definition": {
                **copy.deepcopy(_SHARED["datasets"]["combined"]),
                "splits": {"train": 0.6, "val": 0.2, "test": 0.2, "seed": 42},
            },
        },
    }
    metadata = DatasetMetadata.model_validate(raw)
    assert metadata.managed is not None
    assert metadata.managed.assignments == {"h": "test"}
    assert "splits" not in metadata.managed.definition.model_dump()


def test_dataset_definition_still_rejects_a_splits_key() -> None:
    with pytest.raises(ValidationError):
        DatasetDefinition.model_validate({**copy.deepcopy(_SHARED["datasets"]["combined"]), "splits": {}})


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

"""Portable policy rejects ambiguous sources before any effects run."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cveta2.adapters.files.managed_sources import LocalSourceFiles
from cveta2.domain.managed.evidence import require_complete_evidence
from cveta2.domain.managed.models import (
    ClearMLDestination,
    ManagedError,
    ManagedSnapshot,
    ProjectConfig,
    PublicationSettings,
    SourceDefinition,
    SourceSnapshot,
    dataset_definition,
    definition_fingerprint,
    has_url_userinfo,
    hide_url_userinfo,
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


_PUBLICATION: dict[str, Any] = {
    "clearml": {"project": "Retail/Datasets", "dataset": "retail-shelves", "output_uri": "s3://my-bucket/.clearml"},
    "api_url": "https://classes.example.com/api",
    "empty_classes": [12],
    "s3_roots": ["s3://my-bucket/images"],
}
_RETAIL: dict[str, Any] = {
    "id": 123,
    "name": "Retail shelves",
    "sync_root": "s3://my-bucket/images",
    "publication": _PUBLICATION,
}


def _global(**extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cvat": {"host": "https://cvat.example", "organization": "my-team"},
        "projects": {"retail": copy.deepcopy(_RETAIL)},
        **extra,
    }


def test_publication_block_parses_the_design_example() -> None:
    config = ProjectConfig.model_validate(_global(local_overrides=True))

    publication = config.projects["retail"].publication
    assert config.local_overrides is True
    assert publication is not None
    assert publication.clearml.output_uri == "s3://my-bucket/.clearml"
    assert publication.empty_classes == [12]
    assert publication.s3_roots == ["s3://my-bucket/images"]


@pytest.mark.parametrize(
    ("drop", "loc"),
    [
        (("clearml", "project"), ("projects", "retail", "publication", "clearml", "project")),
        (("clearml", "dataset"), ("projects", "retail", "publication", "clearml", "dataset")),
        (("api_url",), ("projects", "retail", "publication", "api_url")),
    ],
)
def test_publication_requires_project_dataset_and_api_url(drop: tuple[str, ...], loc: tuple[str, ...]) -> None:
    raw = _global()
    node = raw["projects"]["retail"]["publication"]
    for key in drop[:-1]:
        node = node[key]
    del node[drop[-1]]

    with pytest.raises(ValidationError) as error:
        ProjectConfig.model_validate(raw)

    assert loc in [item["loc"] for item in error.value.errors()]


def test_publication_api_url_rejects_credentials() -> None:
    raw = _global()
    raw["projects"]["retail"]["publication"]["api_url"] = "https://u:p@x/api"

    with pytest.raises(ValidationError, match="without embedded credentials"):
        ProjectConfig.model_validate(raw)


@pytest.mark.parametrize("output_uri", ["s3://key:secret@bucket/x", ""])
def test_output_uri_rejects_embedded_credentials_and_empty(output_uri: str) -> None:
    with pytest.raises(ValidationError):
        ClearMLDestination(project="p", dataset="d", output_uri=output_uri)


# Secrets often hold an unencoded "/", "?" or "#", which ends the authority for urlsplit.
_USERINFO = [
    "https://u:p@cvat.example.com",
    "https://user@cvat.example.com",
    "s3://AKIAEXAMPLE:wJalr/K7MDENG@bucket/.clearml",
    "https://user:pa/ss@cvat.example.com",
    "https://user:pa?ss@cvat.example.com",
    "https://user:p#ss@cvat.example.com",
    "https://u:p@[::1",
    "user:pass@cvat.example.com",
    "key:secret@bucket/x",
    # A secret that starts with digits looks like a port; it is flagged all the same.
    "https://u:12/34@cvat.example.com",
]


@pytest.mark.parametrize("value", _USERINFO)
def test_url_userinfo_is_detected(value: str) -> None:
    assert has_url_userinfo(value)


@pytest.mark.parametrize(
    "value",
    [
        "https://cvat.example.com/a@b",
        "https://classes.example.com/api?x=a@b",
        "https://classes.example.com/api#a@b",
        "s3://minio:9000/bucket/x",
        "s3://bucket/prefix",
        "bare/prefix",
        "https://[::1]:8080/api",
    ],
)
def test_an_at_sign_in_the_path_or_query_is_not_userinfo(value: str) -> None:
    assert not has_url_userinfo(value)
    assert hide_url_userinfo(value) == value


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("s3://AKIAEXAMPLE:wJalr/K7MDENG@bucket/.clearml", "s3://***@bucket/.clearml"),
        ("https://user:p#ss@cvat.example.com", "https://***@cvat.example.com"),
        ("https://u:p@[::1", "https://***@[::1"),
        ("user:pass@cvat.example.com", "***@cvat.example.com"),
        # Cannot be split and has no "@": hidden whole.
        ("https://[::1", "***"),
    ],
)
def test_hide_url_userinfo(value: str, shown: str) -> None:
    assert hide_url_userinfo(value) == shown


@pytest.mark.parametrize("value", [v for v in _USERINFO if v.startswith("https://")])
def test_publication_api_url_rejects_every_userinfo_form(value: str) -> None:
    raw = _global()
    raw["projects"]["retail"]["publication"]["api_url"] = value

    with pytest.raises(ValidationError, match="without embedded credentials"):
        ProjectConfig.model_validate(raw)


@pytest.mark.parametrize("host", [v for v in _USERINFO if v.startswith("https://")])
def test_cvat_host_rejects_every_userinfo_form(host: str) -> None:
    raw = _global()
    raw["cvat"]["host"] = host

    with pytest.raises(ValidationError, match="without credentials"):
        ProjectConfig.model_validate(raw)


@pytest.mark.parametrize("output_uri", _USERINFO)
def test_output_uri_rejects_every_userinfo_form(output_uri: str) -> None:
    with pytest.raises(ValidationError, match="without embedded credentials"):
        ClearMLDestination(project="p", dataset="d", output_uri=output_uri)


def test_output_uri_refuses_an_unparsable_uri() -> None:
    with pytest.raises(ValidationError, match="without embedded credentials"):
        ClearMLDestination(project="p", dataset="d", output_uri="s3://[bad")


@pytest.mark.parametrize(("field", "message"), [("api_url", "without embedded credentials"), ("host", "CVAT host")])
def test_http_urls_refuse_an_unparsable_url(field: str, message: str) -> None:
    raw = _global()
    if field == "host":
        raw["cvat"]["host"] = "https://[bad"
    else:
        raw["projects"]["retail"]["publication"]["api_url"] = "https://[bad/api"

    with pytest.raises(ValidationError, match=message):
        ProjectConfig.model_validate(raw)


def test_url_validators_accept_an_at_sign_in_the_path_or_query() -> None:
    raw = _global()
    raw["projects"]["retail"]["publication"]["api_url"] = "https://classes.example.com/api?owner=a@b"
    raw["projects"]["retail"]["publication"]["clearml"]["output_uri"] = "s3://bucket/team@lab/.clearml"

    publication = ProjectConfig.model_validate(raw).projects["retail"].publication
    assert publication is not None
    assert publication.api_url == "https://classes.example.com/api?owner=a@b"


def test_new_fields_are_not_serialized_at_default() -> None:
    config = ProjectConfig.model_validate(
        {"schema_version": 1, "cvat": {"host": "https://cvat.example"}, "projects": {"a": {"id": 1}}}
    )
    publication = PublicationSettings(
        clearml=ClearMLDestination(project="p", dataset="d"), api_url="https://classes.example.com/api"
    )

    dumped = config.model_dump()
    assert "local_overrides" not in dumped
    assert "publication" not in dumped["projects"]["a"]
    assert ClearMLDestination(project="p", dataset="d").model_dump(mode="json") == {"project": "p", "dataset": "d"}
    assert "s3_roots" not in publication.model_dump()
    assert "output_uri" not in publication.model_dump()["clearml"]


def test_existing_definition_fingerprint_is_unchanged() -> None:
    # Literal digest of _fingerprints()[1] computed on the branch head before Task 1 changed models.py.
    assert _fingerprints()[1] == "0ae2d127ec5a4fad5f76e52ae031b7c83de2d81c30420d71bdb0f9b13689936e"


_COLLISION = "ClearML destination pairs must be unique: Retail/Datasets/retail-shelves"


def _shelves_dataset(clearml: dict[str, str]) -> dict[str, Any]:
    return {
        "sources": [{"name": "retail", "type": "cvat", "project": "retail"}],
        "api_url": "https://classes.example.com/api",
        "clearml": clearml,
    }


def test_destination_pairs_unique_across_projects_and_datasets() -> None:
    raw = _global(datasets={"shelves": _shelves_dataset({"project": "Retail/Datasets", "dataset": "retail-shelves"})})
    with pytest.raises(ValidationError, match=_COLLISION):
        ProjectConfig.model_validate(raw)

    raw = _global()
    raw["projects"]["second"] = {"id": 124, "publication": copy.deepcopy(_PUBLICATION)}
    with pytest.raises(ValidationError, match=_COLLISION):
        ProjectConfig.model_validate(raw)


def test_dataset_clearml_accepts_optional_output_uri() -> None:
    raw = _global(
        datasets={
            "shelves": _shelves_dataset({"project": "Other", "dataset": "x", "output_uri": "gs://bucket/.clearml"})
        }
    )

    config = ProjectConfig.model_validate(raw)

    assert config.datasets["shelves"].clearml.output_uri == "gs://bucket/.clearml"

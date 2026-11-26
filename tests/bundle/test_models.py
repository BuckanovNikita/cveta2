"""Bundle policy regression contracts."""

import pytest
from pydantic import ValidationError

from cveta2.domain.bundle.models import ApiClass, ClassInfo, DatasetMetadata, ImageRoots
from cveta2.domain.class_registry import registry_fingerprint
from cveta2.domain.managed.models import ClearMLDestination


@pytest.mark.parametrize("enabled", ["techClass", "isPeriodical", "isCritical"])
def test_registry_aliases_preserve_external_records(enabled: str) -> None:
    record = {
        "id": 4,
        "number": 93,
        "name": "Царапина",
        "techClass": enabled == "techClass",
        "isPeriodical": enabled == "isPeriodical",
        "isCritical": enabled == "isCritical",
        "threshold": 1.0,
    }

    parsed = ApiClass.model_validate(record)

    assert parsed.tech_class is record["techClass"]
    assert parsed.is_periodical is record["isPeriodical"]
    assert parsed.is_critical is record["isCritical"]
    assert parsed.model_dump() == record
    assert parsed.model_dump(mode="json") == record
    assert ApiClass.model_validate_json(parsed.model_dump_json()) == parsed


def test_missing_registry_flags_read_as_false_and_hash_like_explicit_false() -> None:
    explicit = {
        "id": 626,
        "number": 102,
        "name": "Непрорезанная кромка",
        "techClass": False,
        "isPeriodical": False,
        "isCritical": False,
        "threshold": 1.0,
    }
    bare = {"id": 626, "number": 102, "name": "Непрорезанная кромка", "threshold": 1.0}

    parsed = ApiClass.model_validate(bare)

    assert (parsed.tech_class, parsed.is_periodical, parsed.is_critical) == (False, False, False)
    assert parsed.model_dump(mode="json") == explicit
    assert registry_fingerprint([parsed]) == registry_fingerprint([ApiClass.model_validate(explicit)])


@pytest.mark.parametrize("flag", ["techClass", "isPeriodical", "isCritical"])
@pytest.mark.parametrize("value", ["false", 0, None])
def test_present_registry_flags_must_be_json_booleans(flag: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ApiClass.model_validate({"id": 4, "number": 93, "name": "Царапина", "threshold": 1.0, flag: value})


def test_api_uses_distinct_number_and_id_and_rejects_boolean_identity() -> None:
    record = {
        "id": 4,
        "number": 93,
        "name": "Царапина",
        "techClass": False,
        "isPeriodical": True,
        "isCritical": False,
        "threshold": 1.0,
    }
    assert ApiClass.model_validate(record).number == 93
    with pytest.raises(ValidationError):
        ApiClass.model_validate({**record, "number": True})


def test_metadata_preserves_unicode_and_rejects_secret_urls_and_unknown_fields() -> None:
    metadata = DatasetMetadata(
        api_url="https://example.org/classes",
        classes={"Царапина": ClassInfo(prod_id=93, alt_names=["Старое имя"])},
        images=ImageRoots(local_root=["/data/images"]),
    )
    assert metadata.model_dump()["classes"]["Царапина"]["alt_names"] == ["Старое имя"]
    with pytest.raises(ValidationError):
        DatasetMetadata.model_validate({**metadata.model_dump(), "api_url": "https://user:secret@host/api"})
    with pytest.raises(ValidationError):
        ClassInfo.model_validate({"prod_id": 93, "empty": "false"})
    with pytest.raises(ValidationError):
        ClassInfo.model_validate({"prod_id": 93, "empti": True})


def test_metadata_clearml_block_round_trips_and_omits_absent_values() -> None:
    metadata = DatasetMetadata(
        clearml=ClearMLDestination(project="Retail/Datasets", dataset="retail-shelves"),
        api_url="https://classes.example.com/api",
        classes={},
    )
    dump = metadata.model_dump()
    assert dump["clearml"] == {"project": "Retail/Datasets", "dataset": "retail-shelves"}
    assert next(iter(dump)) == "clearml"
    assert "clearml" not in DatasetMetadata(api_url="https://classes.example.com/api", classes={}).model_dump()
    data = {
        "clearml": {
            "project": "Retail/Datasets",
            "dataset": "retail-shelves",
            "output_uri": "s3://my-bucket/.clearml",
        },
        "api_url": "https://classes.example.com/api",
        "classes": {},
        "images": {"local_root": [], "s3_root": []},
    }
    parsed = DatasetMetadata.model_validate(data)
    assert parsed.clearml == ClearMLDestination(
        project="Retail/Datasets", dataset="retail-shelves", output_uri="s3://my-bucket/.clearml"
    )
    assert parsed.model_dump() == data

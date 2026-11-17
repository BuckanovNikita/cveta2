"""Bundle policy regression contracts."""

import pytest
from pydantic import ValidationError

from cveta2.domain.bundle.models import ApiClass, ClassInfo, DatasetMetadata, ImageRoots


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

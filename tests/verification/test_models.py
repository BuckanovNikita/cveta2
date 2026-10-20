"""Public report and option behavior."""

import pandas as pd
import pytest
from pydantic import ValidationError


def test_options_reject_invalid_threshold_and_unknown_settings() -> None:
    from cveta2.domain.verification.models import ValidationOptions

    for threshold in (0, -1, 1.1, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            ValidationOptions(iou_threshold=threshold)
    with pytest.raises(ValidationError):
        ValidationOptions.model_validate({"typo": True})


def test_result_reasons_use_positions_instead_of_duplicate_index_labels() -> None:
    from cveta2.domain.verification.models import Issue, ValidationResult

    result = ValidationResult(
        profile="cveta2",
        clean=pd.DataFrame(),
        broken=pd.DataFrame({"a": [1, 2]}, index=[9, 9]),
        clean_row_positions=(),
        broken_row_positions=(0, 1),
        issues=(Issue(code="bad", message="Bad value", row_position=1),),
        input_row_count=2,
    )
    assert result.reasons_for(0) == ()
    assert result.reasons_for(1)[0].code == "bad"
    assert not result.is_valid

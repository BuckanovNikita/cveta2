"""Reasons are actionable without looking up internal check names."""

import pandas as pd

from cveta2.composition.verification import ValidationOptions, validate_dataframe


def test_bad_coordinate_reason_explains_required_value() -> None:
    frame = pd.DataFrame(
        {
            "image_name": ["a.jpg"],
            "image_path": ["a.jpg"],
            "instance_label": ["cat"],
            "split": ["train"],
            "bbox_x_tl": ["bad"],
            "bbox_y_tl": [0],
            "bbox_x_br": [10],
            "bbox_y_br": [10],
        }
    )
    result = validate_dataframe(
        frame, profile="clearml-yolo", options=ValidationOptions(emit_warnings=False)
    )
    reason = next(
        issue for issue in result.reasons_for(0) if issue.code == "invalid_coordinate"
    )
    assert "finite number" in reason.message
    assert "bbox_x_tl" in reason.message

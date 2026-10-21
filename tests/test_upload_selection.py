"""Upload and recovery must agree on eligible rows without changing the input."""

from dataclasses import replace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from cveta2.application.client.session import TaskWriteSession
from cveta2.application.ports.cvat import CvatApiPort
from cveta2.application.ports.dtos import RawAnnotations
from cveta2.application.use_cases.upload import (
    UploadDependencies,
    UploadOptions,
    UploadOutcome,
    UploadPlan,
    UploadRequest,
    _StagedUpload,
    _verify_existing_shapes,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import LabelInfo
from cveta2.domain.upload import validate_upload_boxes
from tests.helpers import client_with_api, make_raw_shape


@pytest.mark.parametrize(
    "value_type",
    [
        UploadDependencies,
        UploadOptions,
        UploadOutcome,
        UploadPlan,
        UploadRequest,
        _StagedUpload,
    ],
)
def test_upload_values_keep_their_serialized_module_identity(
    value_type: type[object],
) -> None:
    """Moving class definitions must preserve their established qualified names."""
    assert value_type.__module__ == "cveta2.application.use_cases.upload"


def test_write_and_resume_keep_selected_row_order_and_multiplicity() -> None:
    """Mixed skipped rows and duplicate indexes cannot alter shape identity."""
    frame = pd.DataFrame(
        {
            "image_name": [
                "b.jpg",
                "gone.jpg",
                "blank.jpg",
                "a.jpg",
                "nil.jpg",
                "a.jpg",
            ],
            "instance_label": ["car", "car", "  ", "car", None, "car"],
            "instance_shape": ["box", "deleted", "box", "box", "box", "box"],
            "bbox_x_tl": [1, None, None, 1, None, 1],
            "bbox_y_tl": [2, None, None, 2, None, 2],
            "bbox_x_br": [3, None, None, 3, None, 3],
            "bbox_y_br": [4, None, None, 4, None, 4],
        },
        index=[7, 7, 9, 7, 9, 7],
    )
    original = frame.copy(deep=True)
    api = MagicMock(spec=CvatApiPort)
    session = TaskWriteSession(
        api,
        99,
        _name_to_frame={"a.jpg": 0, "b.jpg": 1},
        _labels=[LabelInfo(id=7, name="car")],
    )

    validate_upload_boxes(frame)
    assert client_with_api(api).upload_task_annotations(99, frame, session=session) == 3
    shapes = api.put_task_shapes.call_args.args[1]
    assert [(shape.frame, shape.label_id, shape.points) for shape in shapes] == [
        (1, 7, [1, 2, 3, 4]),
        (0, 7, [1, 2, 3, 4]),
        (0, 7, [1, 2, 3, 4]),
    ]
    stored = make_raw_shape(label_id=7, points=[1, 2, 3, 4])
    api.get_task_annotations.return_value = RawAnnotations(
        shapes=[stored, replace(stored, frame=1), stored]
    )
    api.put_task_shapes.reset_mock()

    assert _verify_existing_shapes(99, frame, session) == 3
    api.put_task_shapes.assert_not_called()
    pd.testing.assert_frame_equal(frame, original)


def test_invalid_selected_row_retains_original_index_in_diagnostic() -> None:
    """Validation must identify the eligible bad row before any metadata read."""
    frame = pd.DataFrame(
        {
            "image_name": ["ignored.jpg", "bad.jpg"],
            "instance_label": ["car", "car"],
            "instance_shape": ["deleted", "box"],
        },
        index=[23, 23],
    )
    api = MagicMock(spec=CvatApiPort)

    with pytest.raises(Cveta2Error, match=r"строка 23, изображение 'bad.jpg'") as error:
        client_with_api(api).upload_task_annotations(99, frame)

    assert "ignored.jpg" not in str(error.value)
    assert api.mock_calls == []


@pytest.mark.parametrize("row_index", [[23], [23, 23]])
def test_missing_labels_skip_caller_indexes_without_reading_metadata(
    row_index: list[int],
) -> None:
    """Image-only caller frames retain their index through upload and resume."""
    frame = pd.DataFrame({"image_name": ["a.jpg"] * len(row_index)}, index=row_index)
    original = frame.copy(deep=True)
    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations()

    validate_upload_boxes(frame)
    assert client_with_api(api).upload_task_annotations(99, frame) == 0
    assert _verify_existing_shapes(99, frame, TaskWriteSession(api, 99)) == 0

    api.get_task_data_meta.assert_not_called()
    api.get_task_labels.assert_not_called()
    api.get_task_jobs.assert_not_called()
    api.put_task_shapes.assert_not_called()
    api.get_task_annotations.assert_called_once_with(99)
    pd.testing.assert_frame_equal(frame, original)


def test_empty_string_typed_annotation_schema_skips_box_reductions() -> None:
    """An empty lexical table is valid regardless of its pandas column dtype."""
    frame = pd.DataFrame(
        {
            column: pd.Series(dtype="string")
            for column in (
                "image_name",
                "instance_label",
                "bbox_x_tl",
                "bbox_y_tl",
                "bbox_x_br",
                "bbox_y_br",
            )
        }
    )
    original = frame.copy(deep=True)
    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations()

    validate_upload_boxes(frame)
    assert client_with_api(api).upload_task_annotations(99, frame) == 0
    assert _verify_existing_shapes(99, frame, TaskWriteSession(api, 99)) == 0

    api.get_task_data_meta.assert_not_called()
    api.get_task_labels.assert_not_called()
    api.put_task_shapes.assert_not_called()
    pd.testing.assert_frame_equal(frame, original)

"""Tests for cvat_sdk request builders.

These builders never run under ``FakeCvatApi`` — the fake implements the port
directly, so nothing in the unit suite exercised the real SDK request objects.
Each test compares ``to_dict()`` against a literal payload, which is the only
way to observe both a wrong value *and* a dropped keyword.
"""

from __future__ import annotations

import pytest

from cveta2._client.dtos import (
    LabelPatch,
    NewIssue,
    NewShape,
    RawShape,
    UploadTaskSpec,
)
from cveta2._client.sdk_requests import (
    _build_label_patch_request,
    build_data_request,
    build_delete_shapes_payload,
    build_deleted_frames_request,
    build_issue_request,
    build_job_patch_request,
    build_labels_patch_request,
    build_new_shapes_payload,
    build_task_write_request,
)


def make_spec() -> UploadTaskSpec:
    """Spec whose ``segment_size`` / ``image_quality`` differ from the defaults.

    ``UploadTaskSpec`` defaults both to 100; leaving them there would make a
    mutant that hardcodes or drops either keyword indistinguishable from the
    original.
    """
    return UploadTaskSpec(
        project_id=3,
        name="upload-2026-05",
        server_files=["p/b.jpg", "p/a.jpg"],
        cloud_storage_id=7,
        segment_size=42,
        image_quality=77,
    )


def test_build_task_write_request_carries_the_whole_spec() -> None:
    assert build_task_write_request(make_spec()).to_dict() == {
        "name": "upload-2026-05",
        "project_id": 3,
        "segment_size": 42,
    }


def test_build_data_request_uses_predefined_sorting() -> None:
    spec = make_spec()
    request = build_data_request(spec)
    assert request.sorting_method.value == "predefined"
    assert request.server_files == ["p/b.jpg", "p/a.jpg"]


def test_build_data_request_pins_cloud_storage_and_caching() -> None:
    """``cloud_storage_id`` and ``use_cache`` decide where CVAT reads the images.

    Dropping the storage id makes CVAT look for the files on its own share, and
    ``use_cache=False`` makes it materialise every chunk on disk; neither is
    visible through ``sorting_method`` or ``server_files``.
    """
    assert build_data_request(make_spec()).to_dict() == {
        "image_quality": 77,
        "server_files": ["p/b.jpg", "p/a.jpg"],
        "cloud_storage_id": 7,
        "use_cache": True,
        "sorting_method": "predefined",
    }


def test_build_new_shapes_payload_omits_shape_ids() -> None:
    """New shapes must carry no ``id``: an id turns a create into an update."""
    payload = build_new_shapes_payload(
        [NewShape(frame=2, label_id=9, points=[1.0, 2.0, 3.0, 4.0])]
    )
    assert payload.to_dict() == {
        "shapes": [
            {
                "type": "rectangle",
                "frame": 2,
                "label_id": 9,
                "points": [1.0, 2.0, 3.0, 4.0],
            }
        ]
    }


def test_build_delete_shapes_payload_keeps_the_existing_shape_id() -> None:
    """The ``id`` keyword is the *only* difference from the new-shapes payload.

    A mutant that drops it leaves CVAT with an id-less shape, which the delete
    endpoint treats as a fresh shape: instead of removing the annotation the
    request duplicates it. Nothing else in the payload changes, so only the
    presence of ``id`` can catch that.
    """
    shape = RawShape(
        id=55,
        type="rectangle",
        frame=2,
        label_id=9,
        points=[1.0, 2.0, 3.0, 4.0],
        occluded=False,
        z_order=0,
        rotation=0.0,
        source="manual",
        attributes=[],
        created_by="alice",
    )
    assert build_delete_shapes_payload([shape]).to_dict() == {
        "shapes": [
            {
                "type": "rectangle",
                "frame": 2,
                "label_id": 9,
                "points": [1.0, 2.0, 3.0, 4.0],
                "id": 55,
            }
        ]
    }


def test_build_issue_request_maps_job_id_onto_job() -> None:
    issue = NewIssue(job_id=8, frame=4, position=[1.0, 2.0, 3.0, 4.0], message="fix me")
    assert build_issue_request(issue).to_dict() == {
        "frame": 4,
        "position": [1.0, 2.0, 3.0, 4.0],
        "job": 8,
        "message": "fix me",
    }


def test_build_deleted_frames_request_sends_the_frame_ids() -> None:
    assert build_deleted_frames_request([1, 4]).to_dict() == {"deleted_frames": [1, 4]}


class TestBuildLabelPatchRequest:
    """The four dispatch branches, each asserted as a whole payload.

    A reordered or negated branch here is destructive rather than merely wrong:
    a rename that reaches the ``deleted`` branch removes the label from the
    project and every annotation using it goes with it.
    """

    def test_no_id_creates_a_label_by_name(self) -> None:
        assert _build_label_patch_request(LabelPatch(name="car")).to_dict() == {
            "name": "car"
        }

    def test_deleted_wins_over_a_name_change(self) -> None:
        """The overlapping input that pins the branch *order*.

        With both ``name`` and ``deleted`` set, only the branch order decides
        whether CVAT gets a delete or a rename — and each individual branch is
        correct on its own, so no single-field patch can distinguish them.
        """
        patch = LabelPatch(id=5, name="newname", deleted=True)
        assert _build_label_patch_request(patch).to_dict() == {
            "id": 5,
            "deleted": True,
        }

    def test_id_and_name_renames(self) -> None:
        patch = LabelPatch(id=5, name="newname")
        assert _build_label_patch_request(patch).to_dict() == {
            "id": 5,
            "name": "newname",
        }

    def test_id_without_name_recolors(self) -> None:
        patch = LabelPatch(id=5, color="#00ff00")
        assert _build_label_patch_request(patch).to_dict() == {
            "id": 5,
            "color": "#00ff00",
        }


def test_build_labels_patch_request_wraps_every_patch() -> None:
    request = build_labels_patch_request(
        [LabelPatch(name="car"), LabelPatch(id=5, deleted=True)]
    )
    assert request.to_dict() == {
        "labels": [{"name": "car"}, {"id": 5, "deleted": True}]
    }


class TestBuildJobPatchRequest:
    """Both guards, on and off: an omitted field must not be sent at all."""

    def test_both_fields(self) -> None:
        request = build_job_patch_request(stage="acceptance", state="completed")
        assert request.to_dict() == {"stage": "acceptance", "state": "completed"}

    @pytest.mark.parametrize(
        ("stage", "state", "expected"),
        [
            ("acceptance", None, {"stage": "acceptance"}),
            (None, "completed", {"state": "completed"}),
            (None, None, {}),
        ],
    )
    def test_only_the_provided_fields_are_sent(
        self, stage: str | None, state: str | None, expected: dict[str, str]
    ) -> None:
        assert build_job_patch_request(stage=stage, state=state).to_dict() == expected

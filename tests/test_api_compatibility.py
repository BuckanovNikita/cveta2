"""Supported API identities and serialization survive internal module moves."""

import pickle
from importlib import import_module
from typing import get_type_hints

import pandas as pd
import pytest

import cveta2
from cveta2.interfaces.api import Connection, UploadResult, WhatsNewResult

_API = import_module("cveta2.interfaces.api")
_PUBLIC_API = import_module("cveta2.api")


@pytest.mark.parametrize("name", _API.__all__)
def test_workflow_exports_keep_one_identity(name: str) -> None:
    canonical = getattr(_API, name)
    assert getattr(_PUBLIC_API, name) is canonical
    assert getattr(cveta2, name) is canonical


@pytest.mark.parametrize(
    "value",
    [
        Connection(host="https://cvat.example", organization="team"),
        UploadResult(
            task_id=12,
            task_name="sample",
            url="https://cvat.example/tasks/12",
            images=2,
            deleted=0,
            annotations=3,
            issues=1,
        ),
        WhatsNewResult(tasks=[], cutoff=42),
    ],
)
def test_public_models_keep_their_pickle_path(
    value: Connection | UploadResult | WhatsNewResult,
) -> None:
    payload = pickle.dumps(value, protocol=4)
    assert type(value).__module__ == "cveta2.interfaces.api"
    assert b"cveta2.interfaces.api\x94" in payload
    assert pickle.loads(payload) == value  # noqa: S301 - Locally constructed data.


def test_connection_pickle_from_before_module_split_loads() -> None:
    # Protocol-4 bytes captured from the established frozen/slotted dataclass.
    payload = (
        b"\x80\x04\x956\x00\x00\x00\x00\x00\x00\x00"
        b"\x8c\x15cveta2.interfaces.api\x94\x8c\nConnection\x94"
        b"\x93\x94)\x81\x94]\x94(NNNNNNeb."
    )
    assert pickle.loads(payload) == Connection()  # noqa: S301 - Fixed trusted fixture.


@pytest.mark.parametrize("name", ["UploadResult", "WhatsNewResult"])
def test_historical_model_pickle_globals_resolve(name: str) -> None:
    payload = f"ccveta2.interfaces.api\n{name}\n.".encode()
    assert pickle.loads(payload) is getattr(cveta2, name)  # noqa: S301 - Fixed trusted globals.


def test_runtime_annotations_retain_their_public_types() -> None:
    assert get_type_hints(cveta2.merge)["return"] is pd.DataFrame
    for operation in (cveta2.task_delete, cveta2.task_drop_label):
        assert get_type_hints(operation)["connection"] == Connection | None

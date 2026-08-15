"""Concurrency and resume, against a live CVAT.

Both features are only really tested here. Concurrency's failure mode is
CVAT rate-limiting under parallel load — this stack does that, which is why
``integration_test.sh`` disables xdist — and no fake can produce it. Resume
exists for a task the client lost track of, which means the task has to
actually exist somewhere the client cannot see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2._concurrency import Workers, configure_workers
from cveta2.client import CvatClient
from cveta2.services.fetch import FetchOptions, fetch_project
from cveta2.services.upload import (
    UploadOptions,
    UploadPlan,
    UploadRequest,
    upload_dataset,
)
from cveta2.upload_manifest import compute_fingerprint, list_manifests, load_manifest
from tests.integration.conftest import _make_sdk_client
from tests.integration.test_upload import (
    IMAGE_NAMES,
    _coco8_search_dirs,
    _get_project_and_storage,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.integration

_CVAT_WORKERS = 4


@pytest.fixture
def _parallel_cvat() -> Iterator[None]:
    """Fan out CVAT calls for one test.

    The unit-suite conftest pins every test to one worker so call order
    stays assertable; the whole point here is to undo that and put the
    server under the parallel load that makes it answer 429.
    """
    s3, cvat = Workers.s3, Workers.cvat
    configure_workers(s3=s3, cvat=_CVAT_WORKERS)
    yield
    configure_workers(s3=s3, cvat=cvat)


@pytest.mark.usefixtures("_parallel_cvat")
def test_a_parallel_fetch_survives_rate_limiting(tmp_path: Path) -> None:
    """Fetch every task at once and still get the whole dataset.

    Before the retry policy this could not pass: a 429 was retried zero
    times at any layer, and the fetch aborted. Nothing in the unit suite
    can stand in for it — the fake never rate-limits.
    """
    project_id, project_name, _cs_info, cfg = _get_project_and_storage()
    options = FetchOptions(publish_clearml=False, use_cache=False)

    with CvatClient(cfg) as client:
        serial_ctx = client.prepare_fetch(project_id, project_name=project_name)
        expected_tasks = len(serial_ctx.tasks)
        partition = fetch_project(
            client, project_id, project_name, tmp_path / "out", None, options
        )

    assert expected_tasks > 0
    assert (
        len(partition.dataset) + len(partition.obsolete) + len(partition.in_progress)
        > 0
    )


def _upload_request(
    project_id: int, project_name: str, names: list[str], *, resume: bool
) -> UploadRequest:
    """One upload of *names*, annotated so there are shapes to double."""
    rows = [
        {
            "image_name": name,
            "instance_label": "person",
            "bbox_x_tl": 0.0,
            "bbox_y_tl": 0.0,
            "bbox_x_br": 40.0,
            "bbox_y_br": 40.0,
        }
        for name in names
    ]
    return UploadRequest(
        project_id=project_id,
        project_name=project_name,
        task_name="integration-resume-test",
        plan=UploadPlan(
            annotations=pd.DataFrame(rows), image_names=names, deleted_names=[]
        ),
        options=UploadOptions(search_dirs=_coco8_search_dirs(), segment_size=10),
        dataset_path="integration-resume.csv",
        labels=("person",),
        resume=resume,
    )


class _KilledRunError(RuntimeError):
    """Stands in for the process dying once the task exists."""


def test_resume_continues_a_killed_upload_without_duplicating_it() -> None:
    """Kill an upload after CVAT has the task, then finish it with --resume.

    The duplication this guards against is invisible to a green run: a
    second pass appends a second copy of every shape, because CVAT's
    annotation write is CREATE. Only reading the task back afterwards
    shows it.
    """
    project_id, project_name, _cs_info, cfg = _get_project_and_storage()
    names = IMAGE_NAMES[:2]

    with CvatClient(cfg) as client:
        original = client.api.attach_task_data

        def die(_task_id: int, _spec: object) -> None:
            raise _KilledRunError

        client.api.attach_task_data = die  # type: ignore[assignment]
        try:
            with pytest.raises(_KilledRunError):
                upload_dataset(
                    client,
                    _upload_request(project_id, project_name, names, resume=False),
                )
        finally:
            client.api.attach_task_data = original  # type: ignore[method-assign]

        fingerprint = compute_fingerprint(names, [], ("person",))
        stranded = load_manifest(project_id, fingerprint)
        assert stranded is not None
        assert stranded.task_id is not None

        outcome = upload_dataset(
            client, _upload_request(project_id, project_name, names, resume=True)
        )

    assert outcome.images == len(names)
    # The manifest is the run's own record; CVAT is the judge of the rest.
    assert load_manifest(project_id, fingerprint) is None
    assert list_manifests(project_id) == []

    sdk_client = _make_sdk_client()
    try:
        adapter = SdkCvatApiAdapter(sdk_client)
        assert adapter.get_task_size(outcome.task_id) == len(names)
        shapes = adapter.get_task_annotations(outcome.task_id).shapes
        assert len(shapes) == len(names)
        assert len({shape.frame for shape in shapes}) == len(names)
    finally:
        sdk_client.close()

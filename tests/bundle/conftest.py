"""Shared fakes and the fetch scenario of the bundle preparation and publication tests."""

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest
import yaml
from PIL import Image

from cveta2.adapters.files.bundle import LocalBundleFiles
from cveta2.adapters.files.bundle_paths import LocalRoots
from cveta2.adapters.files.media import LocalMediaInspector
from cveta2.application.ports.dataset_bundle import BundleServices
from cveta2.domain.bundle.models import ApiClass, DatasetParent, Publication, UploadError
from cveta2.domain.bundle.preparation import PrepareOptions


def api_class(number: int, name: str) -> ApiClass:
    """Return one public registry record whose ID differs from its number."""
    return ApiClass(
        id=100 + number,
        number=number,
        name=name,
        techClass=False,
        isPeriodical=False,
        isCritical=False,
        threshold=0.5,
    )


class Classes:
    """An observable class API whose response can change between calls."""

    def __init__(self, extra: Sequence[ApiClass] = ()) -> None:
        """Serve ``cat`` (7) and any extra records."""
        self.records = [api_class(7, "cat"), *extra]

    def fetch(self, _url: str) -> list[ApiClass]:
        return self.records


class Store:
    """Capture actual bytes supplied at the publication boundary."""

    def __init__(self) -> None:
        """Initialize an empty remote lineage."""
        self.directory: Path | None = None
        self.files: tuple[str, ...] = ()
        self.output_uri: str | None = None
        self.parent: DatasetParent | None = None
        self.parent_id: str | None = None
        self.parent_files: dict[str, Path] = {}
        self.published: dict[str, bytes] = {}
        self.calls = 0

    def names(self, _project: str) -> list[str]:
        return []

    def latest(self, _project: str, _name: str) -> DatasetParent | None:
        return self.parent

    def publish(
        self,
        _project: str,
        _name: str,
        parent_id: str | None,
        directory: Path,
        *,
        files: tuple[str, ...],
        output_uri: str | None = None,
    ) -> Publication:
        self.directory = directory
        self.files = files
        self.output_uri = output_uri
        self.parent_id = parent_id
        self.calls += 1
        self.published = {p.name: p.read_bytes() for p in directory.iterdir()}
        return Publication("child", "1.0.0")

    def parent_file(self, _parent: DatasetParent, filename: str) -> Path | None:
        return self.parent_files.get(filename)


class Storage:
    """Record configured root checks and simulate inaccessible roots."""

    def __init__(self) -> None:
        """Track root checks without accessing a remote bucket."""
        self.fail = False
        self.refused: set[str] = set()
        self.checked: list[str] = []

    def check_root(self, root: str) -> None:
        if self.fail or root in self.refused:
            raise UploadError("unavailable root")
        self.checked.append(root)


type Scenario = tuple[Path, PrepareOptions, BundleServices, Store, Classes]

# The destination and class API of the scenario's draft ``dataset.yaml``.
PROJECT = "inspection"
DATASET = "training"
API_URL = "https://example.org/classes"

# Image, its split and the task that annotated it; every image has one cat box.
SCENARIO_IMAGES = (("train.png", "train", 1), ("val.png", "val", 2), ("val2.png", "val", 3))


def write_draft(source: Path, draft: dict[str, object]) -> None:
    """Write ``draft`` as the fetch directory's ``dataset.yaml``."""
    (source / "dataset.yaml").write_text(yaml.safe_dump(draft, sort_keys=False), encoding="utf-8")


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    """Build a completed fetch of three images in three tasks, with literal CSV evidence and a draft.

    The draft names the destination and the class API; the options add only the image roots.
    """
    source = tmp_path / "source"
    source.mkdir()
    images = tmp_path / "images"
    images.mkdir()
    rows = []
    for name, split, task in SCENARIO_IMAGES:
        Image.new("RGB", (32, 32)).save(images / name)
        rows.append(
            {
                "image_name": name,
                "image_path": str(images / name),
                "split": split,
                "instance_label": "cat",
                "bbox_x_tl": "1",
                "bbox_y_tl": "1",
                "bbox_x_br": "20",
                "bbox_y_br": "20",
                "task_id": task,
                "task_completed": True,
                "s3_image_path": f"images/{name}",
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(source / "dataset.csv", index=False)
    for name in ("obsolete", "in_progress", "deleted"):
        frame.iloc[:0].to_csv(source / f"{name}.csv", index=False)
    write_draft(source, {"clearml": {"project": PROJECT, "dataset": DATASET}, "api_url": API_URL})
    options = PrepareOptions(local_roots=(str(images),), s3_roots=("s3://bucket/images",))
    store, classes = Store(), Classes()
    services = BundleServices(
        api=classes,
        datasets=store,
        s3=Storage(),
        roots=LocalRoots(),
        files=LocalBundleFiles(),
        media=LocalMediaInspector(),
    )
    return source, options, services, store, classes

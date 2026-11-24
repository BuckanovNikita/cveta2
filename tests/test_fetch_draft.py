"""The draft ``dataset.yaml`` a full fetch writes, and its gap and class coverage warnings."""

import re
from pathlib import Path

import pandas as pd
import pytest
import yaml

from cveta2.adapters.files.bundle import LocalBundleFiles
from cveta2.application.ports.dataset_bundle import DraftFiles
from cveta2.application.use_cases.fetch_draft import DraftServices, write_fetch_draft
from cveta2.domain.bundle.draft import DatasetDraft, build_draft
from cveta2.domain.bundle.models import UploadError
from cveta2.domain.class_registry import ApiClass
from cveta2.domain.managed.models import ClearMLDestination, PublicationSettings
from cveta2.domain.storage import CloudStorageInfo

STORAGE = CloudStorageInfo(id=1, bucket="my-bucket", prefix="images", endpoint_url="http://minio:9000")
API_URL = "https://classes.example.com/api"


def api_class(number: int, name: str) -> ApiClass:
    return ApiClass(
        id=100 + number,
        number=number,
        name=name,
        techClass=False,
        isPeriodical=False,
        isCritical=False,
        threshold=0.5,
    )


REGISTRY = [api_class(1, "bowl"), api_class(2, "cup"), api_class(12, "plate")]


class FakeClassApi:
    """Return fixed records, or raise, and record every requested URL."""

    def __init__(self, records: list[ApiClass] | None = None, error: Exception | None = None) -> None:
        """Answer with *records*, or raise *error* when it is given."""
        self.records = REGISTRY if records is None else records
        self.error = error
        self.urls: list[str] = []

    def fetch(self, url: str) -> list[ApiClass]:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return self.records


class FailingDraftFiles:
    """Fail the draft write the way a full disk or a read-only directory does."""

    def read_draft(self, _directory: Path) -> DatasetDraft | None:
        return None

    def write_draft(self, directory: Path, _draft: DatasetDraft) -> bool:
        raise OSError(f"No space left on device: {directory / 'dataset.yaml'}")


def publication(*, dataset: str = "retail-shelves", empty_classes: list[int] | None = None) -> PublicationSettings:
    return PublicationSettings(
        clearml=ClearMLDestination(project="Retail/Datasets", dataset=dataset),
        api_url=API_URL,
        empty_classes=[12] if empty_classes is None else empty_classes,
    )


def rows(*labels: str, image_path: str = "/data/images/a.jpg") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "image_name": [f"{index}.jpg" for index in range(len(labels))],
            "image_path": [image_path] * len(labels),
            "instance_label": list(labels),
            "instance_shape": ["box"] * len(labels),
        }
    )


COVERED = rows("bowl", "cup", "bowl")


def write(  # noqa: PLR0913
    output: Path,
    dataset: pd.DataFrame = COVERED,
    *,
    publication: PublicationSettings | None,
    storage: CloudStorageInfo | None = STORAGE,
    images_dir: Path | None = Path("/data/images"),
    classes: FakeClassApi | None = None,
    files: DraftFiles | None = None,
) -> DatasetDraft:
    return write_fetch_draft(
        output,
        dataset,
        project_name="Retail shelves",
        publication=publication,
        storage=storage,
        images_dir=images_dir,
        services=DraftServices(files or LocalBundleFiles(), classes or FakeClassApi()),
    )


def matching(messages: list[str], phrase: str) -> list[str]:
    return [message for message in messages if phrase in message]


def test_known_settings_write_draft_without_gap_warnings(tmp_path: Path, capture_logs: list[str]) -> None:
    settings = publication()
    classes = FakeClassApi()

    draft = write(tmp_path, publication=settings, classes=classes)

    expected = build_draft(settings, STORAGE, Path("/data/images"))
    assert draft == expected
    assert DatasetDraft.model_validate(yaml.safe_load((tmp_path / "dataset.yaml").read_text())) == expected
    assert LocalBundleFiles().read_draft(tmp_path) == expected
    assert classes.urls == [API_URL]
    assert capture_logs == []


def test_missing_publication_warns_with_setup_command(tmp_path: Path, capture_logs: list[str]) -> None:
    classes = FakeClassApi()

    draft = write(tmp_path, publication=None, storage=None, classes=classes)

    (warning,) = capture_logs
    assert "cveta2 setup --global --project 'Retail shelves'" in warning
    assert "cveta2 verify" in warning
    assert draft.clearml is None
    assert draft.api_url is None
    stored = yaml.safe_load((tmp_path / "dataset.yaml").read_text())
    assert "clearml" not in stored
    assert "api_url" not in stored
    assert classes.urls == []


def test_missing_publication_keeps_the_storage_output_uri(tmp_path: Path, capture_logs: list[str]) -> None:
    draft = write(tmp_path, publication=None)

    assert draft.clearml is not None
    assert (draft.clearml.project, draft.clearml.dataset) == (None, None)
    assert yaml.safe_load((tmp_path / "dataset.yaml").read_text())["clearml"] == {
        "output_uri": "s3://my-bucket/.clearml"
    }
    assert len(matching(capture_logs, "cveta2 setup --global")) == 1


def test_no_images_warns_about_local_root(tmp_path: Path, capture_logs: list[str]) -> None:
    draft = write(tmp_path, publication=publication(), images_dir=None)

    assert draft.images is not None
    assert draft.images.local_root == []
    (warning,) = capture_logs
    assert "--local-root" in warning


def test_empty_image_path_rows_are_counted(tmp_path: Path, capture_logs: list[str]) -> None:
    dataset = rows("bowl", "cup", "bowl")
    dataset.loc[[0, 2], "image_path"] = ""

    write(tmp_path, dataset, publication=publication())

    (warning,) = capture_logs
    assert "image_path" in warning
    assert re.search(r"\b2\b", warning)
    assert "cveta2 verify" in warning


def test_missing_image_path_column_is_not_a_failure(tmp_path: Path, capture_logs: list[str]) -> None:
    write(tmp_path, pd.DataFrame(), publication=publication())

    assert (tmp_path / "dataset.yaml").is_file()
    assert matching(capture_logs, "image_path") == []


def test_unreachable_class_api_gives_one_warning(tmp_path: Path, capture_logs: list[str]) -> None:
    classes = FakeClassApi(error=UploadError("Class API request failed"))

    write(tmp_path, publication=publication(empty_classes=[99]), classes=classes)

    (warning,) = capture_logs
    assert "Class API request failed" in warning
    assert (tmp_path / "dataset.yaml").is_file()


def test_malformed_api_url_gives_one_warning(tmp_path: Path, capture_logs: list[str]) -> None:
    # PublicationSettings itself refuses a non-HTTP class API, so the settings are
    # built unvalidated: the draft keeps whatever URL it gets, and the
    # DatasetMetadata check of that URL is what this guards.
    settings = PublicationSettings.model_construct(
        clearml=ClearMLDestination(project="Retail/Datasets", dataset="retail-shelves"),
        api_url="ftp://x",
        empty_classes=[12],
        s3_roots=None,
    )

    write(tmp_path, publication=settings)

    (warning,) = capture_logs
    assert "ftp://x" in warning
    assert (tmp_path / "dataset.yaml").is_file()


def test_ambiguous_class_registry_gives_one_warning(tmp_path: Path, capture_logs: list[str]) -> None:
    classes = FakeClassApi([api_class(1, "bowl"), api_class(2, "bowl")])

    write(tmp_path, publication=publication(empty_classes=[]), classes=classes)

    (warning,) = capture_logs
    assert "Duplicate API class name: 'bowl'" in warning
    assert (tmp_path / "dataset.yaml").is_file()


def test_coverage_warnings_name_missing_classes_and_count_excluded_rows(
    tmp_path: Path, capture_logs: list[str]
) -> None:
    write(tmp_path, rows("plate", "plate", "bowl"), publication=publication(empty_classes=[12]))

    assert len(capture_logs) == 2
    (missing,) = matching(capture_logs, "cup")
    assert "empty: true" in missing
    (excluded,) = matching(capture_logs, "исключ")
    assert re.search(r"\b2\b", excluded)
    assert "cup" not in excluded


def test_unknown_empty_class_numbers_give_one_warning(tmp_path: Path, capture_logs: list[str]) -> None:
    write(tmp_path, rows("bowl", "cup"), publication=publication(empty_classes=[12, 77, 99]))

    (warning,) = capture_logs
    assert "[77, 99]" in warning
    assert "cveta2 verify" in warning


def test_replaced_draft_with_different_content_is_announced(tmp_path: Path, capture_logs: list[str]) -> None:
    write(tmp_path, publication=publication())
    first = (tmp_path / "dataset.yaml").read_bytes()

    write(tmp_path, publication=publication())
    assert matching(capture_logs, "dataset.yaml.bak") == []
    assert not (tmp_path / "dataset.yaml.bak").exists()

    write(tmp_path, publication=publication(dataset="retail-shelves-v2"))

    (warning,) = matching(capture_logs, "dataset.yaml.bak")
    assert warning == "Прежний dataset.yaml отличался и сохранён как dataset.yaml.bak."
    assert (tmp_path / "dataset.yaml.bak").read_bytes() == first
    assert yaml.safe_load((tmp_path / "dataset.yaml").read_text())["clearml"]["dataset"] == "retail-shelves-v2"


@pytest.mark.parametrize("files", [FailingDraftFiles(), LocalBundleFiles()], ids=["os-error", "upload-error"])
def test_draft_write_failure_is_a_warning(tmp_path: Path, capture_logs: list[str], files: DraftFiles) -> None:
    # The real writer turns an OSError into UploadError; a directory in place of
    # the draft makes it fail that way.
    (tmp_path / "dataset.yaml").mkdir()

    draft = write(tmp_path, publication=publication(), files=files)

    assert draft == build_draft(publication(), STORAGE, Path("/data/images"))
    (warning,) = capture_logs
    assert "dataset.yaml" in warning

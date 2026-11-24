"""Dataset draft model, its file form and the flag > draft > parent resolution."""

from pathlib import Path

import pytest

from cveta2.adapters.files.bundle import LocalBundleFiles
from cveta2.domain.bundle.draft import (
    DatasetDraft,
    DraftDestination,
    ResolvedPreparation,
    build_draft,
    resolve_preparation,
)
from cveta2.domain.bundle.models import ClassInfo, DatasetMetadata, ImageRoots, UploadError
from cveta2.domain.bundle.preparation import PrepareOptions
from cveta2.domain.managed.models import ClearMLDestination, PublicationSettings
from cveta2.domain.storage import CloudStorageInfo

STORAGE = CloudStorageInfo(id=1, bucket="my-bucket", prefix="images", endpoint_url="http://minio:9000")


def publication(output_uri: str | None = None) -> PublicationSettings:
    return PublicationSettings(
        clearml=ClearMLDestination(project="Retail/Datasets", dataset="retail-shelves", output_uri=output_uri),
        api_url="https://classes.example.com/api",
        empty_classes=[12],
    )


def test_build_draft_matches_design_example() -> None:
    draft = build_draft(publication(), STORAGE, Path("/home/alice/data/images/Retail shelves"))
    assert draft.clearml == DraftDestination(
        project="Retail/Datasets", dataset="retail-shelves", output_uri="s3://my-bucket/.clearml"
    )
    assert draft.api_url == "https://classes.example.com/api"
    assert draft.empty_classes == [12]
    assert draft.images == ImageRoots(
        local_root=["/home/alice/data/images/Retail shelves"], s3_root=["s3://my-bucket/images"]
    )


def test_build_draft_prefers_configured_output_uri_and_s3_roots() -> None:
    settings = publication("s3://other/.clearml").model_copy(update={"s3_roots": ["s3://x/y"]})
    draft = build_draft(settings, STORAGE, None)
    assert draft.clearml is not None
    assert draft.clearml.output_uri == "s3://other/.clearml"
    assert draft.images == ImageRoots(s3_root=["s3://x/y"])


def test_build_draft_without_publication_or_storage() -> None:
    assert build_draft(None, None, None) == DatasetDraft()


def test_build_draft_storage_with_empty_prefix_and_no_publication() -> None:
    draft = build_draft(None, STORAGE.model_copy(update={"prefix": "/"}), None)
    assert draft.clearml == DraftDestination(output_uri="s3://my-bucket/.clearml")
    assert draft.images == ImageRoots(s3_root=["s3://my-bucket"])


FULL = DatasetDraft(
    clearml=DraftDestination(project="D-project", dataset="D-dataset", output_uri="s3://d/.clearml"),
    api_url="https://draft/api",
)


def parent_metadata(images: ImageRoots | None = None) -> DatasetMetadata:
    return DatasetMetadata(
        api_url="https://parent/api",
        classes={"a": ClassInfo(prod_id=5, empty=True)},
        images=images or ImageRoots(),
    )


def resolved(**fields: object) -> ResolvedPreparation:
    values: dict[str, object] = {
        "project": None,
        "dataset_name": None,
        "output_uri": None,
        "api_url": None,
        "class_marks": {},
        "local_roots": (),
        "parent_local_roots": (),
        "s3_roots": (),
    }
    return ResolvedPreparation(**{**values, **fields})  # type: ignore[arg-type]


ALL_FLAGS = PrepareOptions(
    project="F-project", dataset_name="F-dataset", output_uri="s3://f/x", api_url="https://flag/api"
)
NO_FLAGS = PrepareOptions()


@pytest.mark.parametrize(
    ("options", "draft", "parent", "expected"),
    [
        (
            ALL_FLAGS,
            FULL,
            None,
            resolved(project="F-project", dataset_name="F-dataset", output_uri="s3://f/x", api_url="https://flag/api"),
        ),
        (
            NO_FLAGS,
            FULL,
            None,
            resolved(
                project="D-project", dataset_name="D-dataset", output_uri="s3://d/.clearml", api_url="https://draft/api"
            ),
        ),
        (NO_FLAGS, DatasetDraft(clearml=DraftDestination()), parent_metadata(), resolved(api_url="https://parent/api")),
        (NO_FLAGS, None, None, resolved()),
        (NO_FLAGS, DatasetDraft(empty_classes=[3]), None, resolved(class_marks={3: True})),
        (
            PrepareOptions(class_empty={3: False}),
            DatasetDraft(empty_classes=[3]),
            None,
            resolved(class_marks={3: False}),
        ),
        (
            PrepareOptions(class_empty={4: True}),
            DatasetDraft(empty_classes=[3]),
            None,
            resolved(class_marks={3: True, 4: True}),
        ),
        (
            PrepareOptions(class_empty={5: False}),
            None,
            parent_metadata(),
            resolved(api_url="https://parent/api", class_marks={5: False}),
        ),
        (
            PrepareOptions(local_roots=("/f",), s3_roots=("s3://b/p",)),
            DatasetDraft(images=ImageRoots(local_root=["/d", "/f"], s3_root=["s3://b/d"])),
            parent_metadata(ImageRoots(local_root=["/p"], s3_root=["s3://b/p"])),
            resolved(
                api_url="https://parent/api",
                local_roots=("/f", "/d"),
                parent_local_roots=("/p",),
                s3_roots=("s3://b/p", "s3://b/d"),
            ),
        ),
    ],
)
def test_resolve_preparation_precedence(
    options: PrepareOptions, draft: DatasetDraft | None, parent: DatasetMetadata | None, expected: ResolvedPreparation
) -> None:
    assert resolve_preparation(options, draft, parent) == expected


def test_parent_marks_stay_on_the_parent() -> None:
    parent = parent_metadata()
    resolve_preparation(PrepareOptions(class_empty={5: False}), None, parent)
    assert parent.classes["a"].empty is True


def test_draft_yaml_omits_absent_keys(tmp_path: Path) -> None:
    files = LocalBundleFiles()
    draft = DatasetDraft(clearml=DraftDestination(project="P", dataset="D"), images=ImageRoots(s3_root=["s3://b/i"]))
    files.write_draft(tmp_path, draft)
    text = (tmp_path / "dataset.yaml").read_text(encoding="utf-8")
    assert "null" not in text
    assert "output_uri" not in text
    assert "local_root" not in text
    assert files.read_draft(tmp_path) == draft


def test_empty_draft_is_written_as_empty_mapping(tmp_path: Path) -> None:
    files = LocalBundleFiles()
    files.write_draft(tmp_path, DatasetDraft(images=ImageRoots()))
    assert (tmp_path / "dataset.yaml").read_text(encoding="utf-8") == "{}\n"
    assert files.read_draft(tmp_path) == DatasetDraft()


def test_write_draft_backs_up_a_different_draft(tmp_path: Path) -> None:
    files = LocalBundleFiles()
    first, second, third = (DatasetDraft(api_url=f"https://x/{n}") for n in "123")
    backup = tmp_path / "dataset.yaml.bak"
    assert files.write_draft(tmp_path, first) is False
    first_bytes = (tmp_path / "dataset.yaml").read_bytes()
    assert not backup.exists()
    assert files.write_draft(tmp_path, first) is False
    assert not backup.exists()
    assert files.write_draft(tmp_path, second) is True
    assert backup.read_bytes() == first_bytes
    second_bytes = (tmp_path / "dataset.yaml").read_bytes()
    assert files.write_draft(tmp_path, third) is True
    assert backup.read_bytes() == second_bytes


def test_read_draft_absent_returns_none(tmp_path: Path) -> None:
    assert LocalBundleFiles().read_draft(tmp_path) is None


@pytest.mark.parametrize(
    ("text", "field"),
    [("classes: {}\n", "classes"), ("empty_classes: [x]\n", "empty_classes"), ("clearml: {project: ''}\n", "project")],
)
def test_draft_rejects_unknown_or_ill_typed_field_naming_file_and_field(tmp_path: Path, text: str, field: str) -> None:
    (tmp_path / "dataset.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(UploadError, match=rf"dataset\.yaml.*{field}"):
        LocalBundleFiles().read_draft(tmp_path)

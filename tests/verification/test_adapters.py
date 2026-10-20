"""Effects remain external and lexical input and cleanup are explicit."""

from pathlib import Path

import pandas as pd
import pytest
from PIL import Image

from cveta2.adapters.files.media import inspect_images
from cveta2.adapters.files.verification import read_csv_bytes, report_dict, write_report
from cveta2.composition.verification import verify_dataframe
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.verification.models import DatasetInputError, ValidationOptions
from cveta2.domain.verification.validation import validate_dataframe


def row(path: str = "a.jpg", right: int = 10) -> dict[str, object]:
    return {
        "image_name": "a.jpg",
        "image_path": path,
        "instance_label": "001",
        "split": "train",
        "bbox_x_tl": 0,
        "bbox_y_tl": 0,
        "bbox_x_br": right,
        "bbox_y_br": 10,
        "image_width": 20,
        "image_height": 30,
    }


@pytest.mark.parametrize("label", ["001", "NA", "None", "null", "1.0", "label\nnext"])
def test_csv_snapshot_preserves_literal_cells(label: str) -> None:
    text = f'image_name,instance_label\na.jpg,"{label}"\n'
    frame = read_csv_bytes(text.encode())
    assert frame.iloc[0]["instance_label"] == label


@pytest.mark.parametrize(
    "text",
    ["a,a\n1,2\n", ",a\nx,y\n", "a,b\n1\n", "a,b\n1,2,3\n", 'a,b\n"unclosed,2\n', ""],
)
def test_ambiguous_csv_snapshot_raises_library_error(text: str) -> None:
    with pytest.raises(Cveta2Error):
        read_csv_bytes(text.encode())


def test_clipping_requires_explicit_cleanup_and_preserves_input(tmp_path: Path) -> None:
    frame = pd.DataFrame([row(right=21)])
    original = frame.copy(deep=True)
    result = verify_dataframe(
        frame, profile="clearml-yolo", options=ValidationOptions(emit_warnings=False)
    )
    assert result.is_valid
    assert result.requires_cleanup
    assert report_dict(result)["requires_cleanup"] is True
    pd.testing.assert_frame_equal(frame, original)
    write_report(result, tmp_path / "report")
    assert not (tmp_path / "report" / "clean.csv").exists()
    write_report(result, tmp_path / "cleaned", cleanup=True)
    assert (tmp_path / "cleaned" / "clean.csv").exists()
    with pytest.raises(FileExistsError):
        write_report(result, tmp_path / "report")


def test_structural_errors_cannot_be_cleaned_away(tmp_path: Path) -> None:
    result = validate_dataframe(pd.DataFrame({"image_name": ["a.jpg"]}))
    with pytest.raises(DatasetInputError, match="Structural"):
        write_report(result, tmp_path / "output", cleanup=True)
    assert not (tmp_path / "output").exists()


def test_decode_cache_and_orientation_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exif = Image.Exif()
    exif[274] = 6
    image_path = tmp_path / "a.jpg"
    Image.new("RGB", (30, 20)).save(image_path, exif=exif)
    alias = tmp_path / "alias.jpg"
    alias.symlink_to(image_path)
    actual_open = Image.open
    opened: list[object] = []

    def counted_open(path: Path) -> Image.Image:
        opened.append(path)
        return actual_open(path)

    monkeypatch.setattr(Image, "open", counted_open)
    frame = pd.DataFrame([row(str(image_path)), row(str(alias))])
    facts = inspect_images(
        frame, profile="clearml-yolo", options=ValidationOptions(check_images=True)
    )
    assert opened == [image_path]
    assert [fact.size for fact in facts.rows] == [(20, 30), (20, 30)]
    assert [fact.image_format for fact in facts.rows] == ["JPEG", "JPEG"]
    assert facts.rows[1].canonical_path == str(image_path)


def test_inspection_disabled_still_supplies_identity_without_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_open(path: Path) -> Image.Image:
        pytest.fail(f"Unexpected decode {path}")

    monkeypatch.setattr(Image, "open", fail_open)
    facts = inspect_images(
        pd.DataFrame([row("./a.jpg")]),
        profile="clearml-yolo",
        options=ValidationOptions(base_dir=tmp_path),
    )
    assert facts.rows[0].canonical_path == str(tmp_path / "a.jpg")
    assert facts.rows[0].size is None


def test_pure_validation_never_resolves_filesystem_or_emits_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolve(path: Path, *, strict: bool = False) -> Path:
        pytest.fail(f"Unexpected filesystem resolution {path} strict={strict}")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    result = validate_dataframe(pd.DataFrame([row()]), profile="clearml-yolo")
    assert result.is_valid


@pytest.mark.parametrize(
    "uri", ["https://example.org/a.jpg", "s3://bucket/a.jpg", "file:///a.jpg"]
)
def test_remote_media_is_reported_without_network(uri: str) -> None:
    facts = inspect_images(
        pd.DataFrame([row(uri)]),
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True),
    )
    assert facts.rows[0].canonical_path is None
    assert {issue.code for issue in facts.rows[0].issues} == {
        "invalid_local_path",
        "media_unreadable",
    }


def test_missing_and_corrupt_files_report_each_original_position(
    tmp_path: Path,
) -> None:
    (tmp_path / "bad.jpg").write_bytes(b"not an image")
    frame = pd.DataFrame(
        [
            {"image_name": "missing.jpg"},
            {"image_name": "bad.jpg"},
            {"image_name": "bad.jpg"},
        ],
        index=[7, 7, 99],
    )
    facts = inspect_images(
        frame,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, image_root=tmp_path),
    )
    assert [(fact.row_position, fact.issues[0].code) for fact in facts.rows] == [
        (0, "media_missing"),
        (1, "media_unreadable"),
        (2, "media_unreadable"),
    ]


def test_truncated_jpeg_is_decoded_and_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    Image.new("RGB", (30, 40)).save(path)
    path.write_bytes(path.read_bytes()[:-20])
    facts = inspect_images(
        pd.DataFrame([row(str(path))]),
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True),
    )
    assert facts.rows[0].size is None
    assert facts.rows[0].issues[0].code == "media_unreadable"


def test_deleted_cveta_rows_do_not_decode_missing_images(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [{**row(str(tmp_path / "a.jpg")), "instance_shape": "deleted"}]
    )
    facts = inspect_images(
        frame, profile="cveta2", options=ValidationOptions(check_images=True)
    )
    assert not facts.rows[0].issues
    assert facts.rows[0].size is None


def test_requested_media_checks_without_facts_cannot_pass() -> None:
    result = validate_dataframe(
        pd.DataFrame([row()]),
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True),
    )
    assert not result.is_valid
    assert any(issue.code == "media_uninspected" for issue in result.issues)


def test_nul_path_is_a_positional_finding() -> None:
    facts = inspect_images(
        pd.DataFrame([row("invalid\x00.jpg")]),
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True),
    )
    assert any(issue.code == "invalid_local_path" for issue in facts.rows[0].issues)


def test_broken_report_keeps_original_rows_and_collision_free_metadata(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame([{**row(right=0), "__validator_row_position": "keep"}])
    result = verify_dataframe(
        frame, profile="clearml-yolo", options=ValidationOptions(emit_warnings=False)
    )
    write_report(result, tmp_path / "report", cleanup=True)
    broken = pd.read_csv(tmp_path / "report" / "broken.csv", keep_default_na=False)
    assert broken.iloc[0]["__validator_row_position"] == "keep"
    assert broken.iloc[0]["__validator_row_position_"] == 0
    assert broken.iloc[0]["bbox_x_br"] == 0


def test_explicit_cleanup_requires_destination_before_reading(tmp_path: Path) -> None:
    from cveta2.composition.verification import verify

    with pytest.raises(DatasetInputError, match=r"destination|output"):
        verify(tmp_path / "absent.csv", cleanup=True)


def test_csv_context_and_report_are_owned_by_file_adapter(tmp_path: Path) -> None:
    from cveta2.composition.verification import verify

    Image.new("RGB", (20, 30)).save(tmp_path / "a.jpg")
    source = tmp_path / "input.csv"
    frame = pd.DataFrame([row(right=21)])
    frame.to_csv(source, index=False)
    result = verify(
        source,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
        output_dir=tmp_path / "cleaned",
        cleanup=True,
    )
    assert result.requires_cleanup
    assert (tmp_path / "cleaned" / "clean.csv").is_file()
    assert pd.read_csv(source).iloc[0]["bbox_x_br"] == 21


def test_application_csv_workflow_uses_injected_file_and_media_ports() -> None:
    from cveta2.application.ports.verification import (
        LoadedVerification,
        VerificationRequest,
    )
    from cveta2.application.use_cases.verify import verify
    from cveta2.domain.verification.models import (
        MediaInspection,
        Profile,
        ValidationResult,
    )

    events: list[str] = []
    context = ValidationOptions(base_dir=Path("/captured"))
    frame = pd.DataFrame([row()])

    class Files:
        def load(
            self, path: str | Path, options: ValidationOptions
        ) -> LoadedVerification:
            assert path == "input.csv"
            assert options.base_dir is None
            events.append("load")
            return LoadedVerification(frame, Path("input.csv"), context)

        def persist(
            self,
            result: ValidationResult,
            directory: str | Path,
            *,
            cleanup: bool,
            input_path: Path,
        ) -> None:
            assert result.is_valid
            assert directory == "output"
            assert cleanup
            assert input_path == Path("input.csv")
            events.append("persist")

        def warn(self, result: ValidationResult) -> None:
            assert result.is_valid
            events.append("warn")

    class Inspector:
        def inspect(
            self, actual: pd.DataFrame, *, profile: Profile, options: ValidationOptions
        ) -> MediaInspection:
            assert actual is frame
            assert profile == "clearml-yolo"
            assert options is context
            events.append("inspect")
            return MediaInspection()

    result = verify(
        VerificationRequest(
            "input.csv", profile="clearml-yolo", output_dir="output", cleanup=True
        ),
        files=Files(),
        inspector=Inspector(),
    )
    assert result.is_valid
    assert events == ["load", "inspect", "persist", "warn"]

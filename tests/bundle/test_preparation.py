"""Bundle preparation writes real files once; publication runs against fake remote ports."""

import json
import os
import threading
from pathlib import Path

import pytest
import yaml

from cveta2.adapters.files.archive import unpack_sources
from cveta2.adapters.files.bundle import LocalBundleFiles
from cveta2.application.use_cases.dataset_bundle import prepare_dataset, upload_dataset
from cveta2.domain.bundle.models import Publication, UploadError
from cveta2.domain.bundle.preparation import PUBLISHED_NAMES, SOURCE_NAMES, MissingDecisions
from tests.bundle.conftest import Scenario


def _duplicate_first_row(source: Path) -> None:
    path = source / "dataset.csv"
    original = path.read_text()
    path.write_text(original + original.splitlines()[1] + "\n")


def test_bundle_layout_has_archive_and_no_preparation_record(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    original = {p.name: p.read_bytes() for p in source.iterdir()}
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.ready
    assert store.calls == 0
    assert {p.name for p in prepared.iterdir()} == {
        "sources.tar.gz",
        "broken-images.csv",
        "report.json",
        "dataset.csv",
        "dataset.yaml",
        "tasks.yaml",
    }
    assert unpack_sources((prepared / "sources.tar.gz").read_bytes()) == {name: original[name] for name in SOURCE_NAMES}
    metadata_text = (prepared / "dataset.yaml").read_text(encoding="utf-8")
    assert metadata_text.startswith("clearml:")
    assert yaml.safe_load(metadata_text)["clearml"] == {"project": options.project, "dataset": options.dataset_name}
    report = json.loads((prepared / "report.json").read_bytes())
    assert report["parent"] is None
    assert report["destination"] == {"project": options.project, "dataset": options.dataset_name}
    assert report["pending"] == []
    assert report["class_marks"] == []
    assert report["dropped_local_roots"] == []
    assert report["split_prefilled"] == 0
    assert upload_dataset(prepared, services).dataset_id == "child"
    assert store.files == PUBLISHED_NAMES
    assert set(store.published) == set(PUBLISHED_NAMES)
    assert {p.name: p.read_bytes() for p in source.iterdir()} == original


def test_missing_class_decisions_are_structured_and_prompt_free(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    options = options.model_copy(update={"accept_default_classes": False})
    with pytest.raises(MissingDecisions) as caught:
        prepare_dataset(source, tmp_path / "prepared", options, services)
    assert any(d.kind == "class_empty" and d.class_id == 7 for d in caught.value.decisions)
    assert store.calls == 0


def test_report_only_does_not_create_uploadable_cleaned_bundle(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    _duplicate_first_row(source)
    result = prepare_dataset(source, tmp_path / "report", options.model_copy(update={"clean": False}), services)
    assert not result.ready
    assert result.validation.result.requires_cleanup
    assert not (tmp_path / "report" / "dataset.csv").exists()
    clean = options.model_copy(update={"clean": True})
    result = prepare_dataset(source, tmp_path / "prepared", clean, services)
    assert result.ready
    assert upload_dataset(tmp_path / "prepared", services).dataset_id == "child"
    assert store.calls == 1


def test_blocked_preparation_writes_archive_and_report_only(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    _duplicate_first_row(source)
    prepared = tmp_path / "blocked"
    result = prepare_dataset(source, prepared, options.model_copy(update={"clean": False}), services)
    assert not result.ready
    assert any(blocker.startswith("Нужна очистка:") for blocker in result.blockers)
    assert {p.name for p in prepared.iterdir()} == {"sources.tar.gz", "broken-images.csv", "report.json"}
    report = json.loads((prepared / "report.json").read_bytes())
    assert report["ready"] is False
    assert report["blockers"] == list(result.blockers)


def test_existing_destination_is_preserved(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    directory = tmp_path / "prepared"
    directory.mkdir()
    (directory / "owned.txt").write_text("keep")
    with pytest.raises(UploadError):
        prepare_dataset(source, directory, options, services)
    assert (directory / "owned.txt").read_text() == "keep"


@pytest.mark.parametrize("filename", ["dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv"])
def test_header_only_sources_require_evidence_columns(scenario: Scenario, tmp_path: Path, filename: str) -> None:
    source, options, services, store, _classes = scenario
    (source / filename).write_text("unexpected\n")
    with pytest.raises(UploadError, match=r"column|header"):
        prepare_dataset(source, tmp_path / "prepared", options, services)
    assert store.calls == 0


def test_invalid_api_configuration_is_a_library_error(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    with pytest.raises(UploadError, match=r"API|metadata|URL"):
        prepare_dataset(
            source,
            tmp_path / "prepared",
            options.model_copy(update={"api_url": "bad-url"}),
            services,
        )
    assert store.calls == 0


def test_private_stage_is_removed_on_publication_failure(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    stages: list[Path] = []

    def fail_publish(
        _project: str,
        _name: str,
        _parent: str | None,
        directory: Path,
        *,
        files: tuple[str, ...],
        output_uri: str | None = None,
    ) -> Publication:
        assert files
        assert output_uri is None
        stages.append(directory)
        assert directory.is_dir()
        raise UploadError("child creation failed")

    monkeypatch.setattr(store, "publish", fail_publish)
    with pytest.raises(UploadError, match="creation failed"):
        upload_dataset(prepared, services)
    assert len(stages) == 1
    assert not stages[0].exists()
    assert not (prepared / "publication.json").exists()


@pytest.mark.parametrize("artifact", ["dataset.csv", "dataset.yaml", "sources.tar.gz"])
def test_symlinked_prepared_artifacts_are_rejected(scenario: Scenario, tmp_path: Path, artifact: str) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    target = prepared / artifact
    outside = tmp_path / "original"
    target.rename(outside)
    target.symlink_to(outside)
    with pytest.raises(UploadError, match="nonsymlink"):
        upload_dataset(prepared, services)
    assert store.calls == 0


@pytest.mark.parametrize(
    "text",
    [
        "api_url: x\napi_url: y\n",
        "classes: &classes {cat: *classes}\n",
        "[invalid",
        "true: invalid\n",
        "api_url: https://example.org/classes\nclasses: {}\nimages: " + "[" * 5000 + "]" * 5000 + "\n",
    ],
    ids=["duplicate-key", "recursive-alias", "syntax", "non-text-key", "deep-nesting"],
)
def test_strict_metadata_rejects_ambiguous_yaml(tmp_path: Path, text: str) -> None:
    metadata = tmp_path / "dataset.yaml"
    metadata.write_text(text)
    with pytest.raises(UploadError):
        LocalBundleFiles().read_metadata(metadata)


def test_strict_metadata_checks_reused_aliases_once(tmp_path: Path) -> None:
    levels = 60
    lines = ["api_url: https://example.org/classes", "classes: {}", "x0: &a0 [x, x]"]
    lines += [f"x{level}: &a{level} [*a{level - 1}, *a{level - 1}]" for level in range(1, levels + 1)]
    metadata = tmp_path / "dataset.yaml"
    metadata.write_text("\n".join(lines) + "\n")
    outcome: list[BaseException] = []

    def read() -> None:
        try:
            LocalBundleFiles().read_metadata(metadata)
        except UploadError as error:
            outcome.append(error)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout=10)
    assert not reader.is_alive(), "alias fan-out is re-walked on every reference"
    assert len(outcome) == 1
    assert "x0" in str(outcome[0])


def test_interrupted_write_leaves_no_bundle(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"

    def fail_rename(_source: object, _destination: object) -> None:
        raise OSError("bundle could not be moved into place")

    monkeypatch.setattr(os, "rename", fail_rename)
    with pytest.raises(UploadError, match="could not be moved"):
        prepare_dataset(source, prepared, options, services)
    assert not prepared.exists()
    assert not list(tmp_path.glob(".cveta2-prepare-*"))
    monkeypatch.undo()
    with pytest.raises(UploadError):
        upload_dataset(prepared, services)
    assert store.calls == 0

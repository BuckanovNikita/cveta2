"""The crash record `upload --resume` reads.

Its whole job is to survive the process that wrote it, so the properties
worth pinning are the ones a crash can break: where the file lands, that a
half-written one is never read as valid, and that the frozen decisions come
back out exactly as they went in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cveta2.image_downloader import CloudStorageInfo
from cveta2.upload_manifest import (
    MANIFEST_SCHEMA_VERSION,
    UploadManifest,
    compute_fingerprint,
    delete_manifest,
    get_upload_manifest_dir,
    list_manifests,
    load_manifest,
    new_manifest,
    save_manifest,
)

PROJECT_ID = 7


def _cs_info() -> CloudStorageInfo:
    return CloudStorageInfo(id=1, bucket="b", prefix="images", endpoint_url="")


def _manifest(
    *,
    fingerprint: str = "abc123",
    started_at: str | None = None,
    task_id: int | None = None,
) -> UploadManifest:
    manifest = new_manifest(
        dataset_path="out/dataset.csv",
        fingerprint=fingerprint,
        project_id=PROJECT_ID,
        task_name="upload-1",
        cs_info=_cs_info(),
        name_to_server_file={"a.jpg": "2026-01/a.jpg"},
        task_image_names=["images/2026-01/a.jpg"],
    )
    if started_at is not None:
        manifest.started_at = started_at
    manifest.task_id = task_id
    return manifest


class TestLocation:
    def test_manifests_live_under_the_xdg_cache_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Land under XDG_CACHE_HOME, not in a developer's real cache."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

        directory = get_upload_manifest_dir(PROJECT_ID)

        assert directory == tmp_path / "cache" / "cveta2" / "uploads" / "project_7"

    def test_projects_do_not_share_a_directory(self) -> None:
        """Keep projects apart: `--resume` lists candidates by project."""
        assert get_upload_manifest_dir(1) != get_upload_manifest_dir(2)

    def test_the_default_root_is_the_home_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

        directory = get_upload_manifest_dir(PROJECT_ID)

        assert directory.is_relative_to(Path.home() / ".cache" / "cveta2")


class TestRoundTrip:
    def test_a_saved_manifest_comes_back_field_for_field(self) -> None:
        """The mapping and frame order are decisions a resume must not redo."""
        original = _manifest(task_id=42)

        save_manifest(original)
        loaded = load_manifest(PROJECT_ID, "abc123")

        assert loaded == original

    def test_an_absent_manifest_is_not_an_error(self) -> None:
        assert load_manifest(PROJECT_ID, "nothing-here") is None

    def test_a_manifest_from_another_schema_version_is_ignored(self) -> None:
        """An older layout would resume with fields that mean something else."""
        save_manifest(_manifest())
        path = get_upload_manifest_dir(PROJECT_ID) / "abc123.json"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                f'"schema_version":{MANIFEST_SCHEMA_VERSION}',
                f'"schema_version":{MANIFEST_SCHEMA_VERSION + 1}',
            ),
            encoding="utf-8",
        )

        assert load_manifest(PROJECT_ID, "abc123") is None

    def test_a_truncated_manifest_is_ignored(self) -> None:
        """Exactly what a crash mid-write would leave without the atomic rename."""
        save_manifest(_manifest())
        path = get_upload_manifest_dir(PROJECT_ID) / "abc123.json"
        path.write_text('{"schema_version": 1, "task_', encoding="utf-8")

        assert load_manifest(PROJECT_ID, "abc123") is None

    def test_the_write_is_atomic(self) -> None:
        """No temp file may survive: a stray one would be listed as a manifest."""
        save_manifest(_manifest())

        directory = get_upload_manifest_dir(PROJECT_ID)
        assert [p.name for p in directory.iterdir()] == ["abc123.json"]


class TestListing:
    def test_the_newest_unfinished_upload_comes_first(self) -> None:
        """The mismatch report leads with it, so order is the useful part."""
        save_manifest(_manifest(fingerprint="old", started_at="2026-01-01T00:00:00"))
        save_manifest(_manifest(fingerprint="new", started_at="2026-06-01T00:00:00"))

        assert [m.fingerprint for m in list_manifests(PROJECT_ID)] == ["new", "old"]

    def test_a_project_with_no_directory_lists_nothing(self) -> None:
        assert list_manifests(4242) == []

    def test_an_unreadable_entry_does_not_hide_the_readable_ones(self) -> None:
        save_manifest(_manifest(fingerprint="good"))
        (get_upload_manifest_dir(PROJECT_ID) / "broken.json").write_text(
            "not json", encoding="utf-8"
        )

        assert [m.fingerprint for m in list_manifests(PROJECT_ID)] == ["good"]


class TestDelete:
    def test_deleting_removes_the_entry(self) -> None:
        save_manifest(_manifest())

        delete_manifest(PROJECT_ID, "abc123")

        assert load_manifest(PROJECT_ID, "abc123") is None

    def test_deleting_what_is_not_there_is_not_an_error(self) -> None:
        """An upload that never wrote one still finishes by clearing it."""
        delete_manifest(PROJECT_ID, "never-existed")


class TestFingerprint:
    def test_the_same_frames_and_labels_fingerprint_alike(self) -> None:
        """Order of the CSV rows must not decide whether a resume is found."""
        first = compute_fingerprint(["a.jpg", "b.jpg"], ["d.jpg"], ["car"])
        second = compute_fingerprint(["b.jpg", "a.jpg"], ["d.jpg"], ["car"])

        assert first == second

    @pytest.mark.parametrize(
        ("images", "deleted", "labels"),
        [
            (["a.jpg"], ["d.jpg"], ["car"]),
            (["a.jpg", "b.jpg"], [], ["car"]),
            (["a.jpg"], [], ["car", "person"]),
        ],
        ids=["deleted_differs", "images_differ", "labels_differ"],
    )
    def test_a_different_upload_gets_a_different_fingerprint(
        self, images: list[str], deleted: list[str], labels: list[str]
    ) -> None:
        """Resuming across these would bind the wrong frames to the task."""
        baseline = compute_fingerprint(["a.jpg"], [], ["car"])

        assert compute_fingerprint(images, deleted, labels) != baseline

    def test_the_deleted_and_annotated_lists_are_not_interchangeable(self) -> None:
        """They land in different places in the task, so they cannot collide."""
        assert compute_fingerprint(["a.jpg"], [], []) != compute_fingerprint(
            [], ["a.jpg"], []
        )


def test_started_at_is_timezone_aware() -> None:
    """Manifests sort by this string, and a shared cache spans machines.

    A naive timestamp sorts against an aware one by raw text, so the
    "newest unfinished upload" the mismatch report leads with would be
    whichever machine happened to write in the other format.
    """
    started = _manifest().started_at

    assert started.endswith("+00:00")


def test_describe_marks_an_upload_that_never_reached_cvat() -> None:
    """A manifest without a task id has nothing to point the user at.

    Printing a bare ``None`` there reads as a task literally named None.
    """
    described = _manifest(task_id=None).describe()

    assert "None" not in described


def test_describe_names_the_task_a_resume_would_continue() -> None:
    """It is the only thing telling the user which stranded task is which."""
    described = _manifest(task_id=99).describe()

    assert "99" in described
    assert "out/dataset.csv" in described

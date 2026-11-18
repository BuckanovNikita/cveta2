"""Tests for local image lookup confinement and output exclusion."""

from pathlib import Path

import pytest

from cveta2.adapters.files.image_search import resolve_images


class TestLookupConfinement:
    """A lookup never returns a file outside the searched directory."""

    @pytest.mark.parametrize("escaping", ["parent", "absolute", "nested-parent"])
    def test_escaping_name_is_not_found_and_named_in_a_warning(
        self, tmp_path: Path, capture_logs: list[str], escaping: str
    ) -> None:
        search = tmp_path / "images"
        (search / "sub").mkdir(parents=True)
        (tmp_path / "private.jpg").write_bytes(b"secret")
        # Same basename inside the search tree: the basename fallback must not
        # silently substitute it for the rejected path either.
        (search / "sub" / "private.jpg").write_bytes(b"inside")
        name = {
            "parent": "../private.jpg",
            "absolute": str(tmp_path / "private.jpg"),
            "nested-parent": "sub/../../private.jpg",
        }[escaping]

        found, missing = resolve_images([name, "sub/private.jpg"], [search])

        assert found == {"sub/private.jpg": search / "sub" / "private.jpg"}
        assert missing == [name]
        assert any(name in message for message in capture_logs)


class TestOutputExclusion:
    """Files located under the excluded output directory are never returned."""

    @pytest.mark.parametrize("nested", [False, True])
    def test_file_alias_to_output_does_not_hide_a_later_source(self, tmp_path: Path, *, nested: bool) -> None:
        output = tmp_path / "output"
        output.mkdir()
        old_image = output / "a.jpg"
        old_image.write_bytes(b"old output")
        aliases = tmp_path / "aliases"
        alias_dir = aliases / "nested" if nested else aliases
        alias_dir.mkdir(parents=True)
        (alias_dir / "a.jpg").symlink_to(old_image)
        source = tmp_path / "source"
        source.mkdir()
        (source / "a.jpg").write_bytes(b"current source")

        found, missing = resolve_images(["a.jpg"], [aliases, source], exclude=output)

        assert missing == []
        assert found == {"a.jpg": source / "a.jpg"}
        assert old_image.read_bytes() == b"old output"

    def test_output_copy_is_skipped_in_both_lookup_passes(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        (data / "raw").mkdir(parents=True)
        (data / "yolo" / "images").mkdir(parents=True)
        (data / "raw" / "a.jpg").write_bytes(b"source")
        (data / "yolo" / "images" / "a.jpg").write_bytes(b"old output")
        (data / "yolo" / "images" / "b.jpg").write_bytes(b"old output")

        found, missing = resolve_images(["a.jpg", "yolo/images/b.jpg"], [data], exclude=data / "yolo")

        assert found == {"a.jpg": data / "raw" / "a.jpg"}
        assert missing == ["yolo/images/b.jpg"]

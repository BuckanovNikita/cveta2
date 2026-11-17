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

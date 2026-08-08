"""Tests for the standalone helpers in :mod:`cveta2.config`.

Everything here was previously reached only indirectly (or not at all): the
env-flag readers, the config-path helpers, the project-name sanitizer, the
image-cache resolution chain, the credential guard, and the ``upload`` section
— the only ``SectionConfig`` subclass that uses the base ``_to_raw``.

Several tests deliberately name their config file something other than
``config.yaml``. The autouse ``isolated_config_path`` fixture points
``CVETA2_CONFIG`` at ``tmp_path/"config.yaml"``, so a test that uses that same
name cannot tell an explicitly passed path apart from the env fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from pydantic import ValidationError

from cveta2.config import (
    CvatConfig,
    UploadConfig,
    cache_dir_for_project,
    get_projects_cache_path,
    is_cache_disabled,
    is_clearml_disabled,
    is_interactive_disabled,
    resolve_images_cache_dir,
    should_raise_on_fetch_failure,
)
from cveta2.exceptions import MissingCredentialsError
from tests.helpers import write_config_yaml

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# environment flag readers
# ---------------------------------------------------------------------------


# (variable name, the token that switches the flag on, the reader function)
_ENV_FLAG_READERS: list[tuple[str, str, Callable[[], bool]]] = [
    ("CVETA2_NO_INTERACTIVE", "true", is_interactive_disabled),
    ("CVETA2_DISABLE_CACHE", "true", is_cache_disabled),
    ("CVETA2_RAISE_ON_FAILURE", "true", should_raise_on_fetch_failure),
    ("CVETA2_CLEARML", "false", is_clearml_disabled),
]

# (how to derive the env value from the trigger token, expected reader answer);
# a None mangler means "leave the variable unset".
_ENV_FLAG_CASES: list[tuple[Callable[[str], str] | None, bool]] = [
    (None, False),
    (str, True),
    (str.upper, True),
    (lambda _trigger: "", False),
    (lambda _trigger: "maybe", False),
]


@pytest.mark.parametrize(
    "reader_spec",
    _ENV_FLAG_READERS,
    ids=[variable for variable, _, _ in _ENV_FLAG_READERS],
)
@pytest.mark.parametrize(
    "case",
    _ENV_FLAG_CASES,
    ids=["unset", "exact", "uppercase", "empty", "other_word"],
)
def test_env_flag_reader_matches_only_its_own_variable(
    monkeypatch: pytest.MonkeyPatch,
    reader_spec: tuple[str, str, Callable[[], bool]],
    case: tuple[Callable[[str], str] | None, bool],
) -> None:
    """Pin the variable name, the exact token and the case-insensitive compare.

    The old suite exercised these readers only through their callers, which
    fixed one value each. That left the whole expression open: reading a
    misspelled variable, comparing against a different token, or dropping the
    ``.lower()`` all produced the same answer for the one case under test.
    """
    variable, trigger, reader = reader_spec
    mangle, expected = case
    if mangle is None:
        monkeypatch.delenv(variable, raising=False)
    else:
        monkeypatch.setenv(variable, mangle(trigger))

    assert reader() is expected


# ---------------------------------------------------------------------------
# config path helpers
# ---------------------------------------------------------------------------


def test_projects_cache_sits_next_to_the_given_config_file(tmp_path: Path) -> None:
    """The cache path follows the *passed* config path, not the env fallback.

    ``get_projects_cache_path`` forwards its argument to ``get_config_path``;
    dropping that forward silently relocated the cache to ``CVETA2_CONFIG``'s
    directory, which every earlier test happened to share with ``tmp_path``.
    """
    config_path = tmp_path / "sub" / "custom.yaml"

    assert get_projects_cache_path(config_path) == tmp_path / "sub" / "projects.yaml"


# ---------------------------------------------------------------------------
# project-name sanitizing and image-cache resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("project_name", "expected_dir"),
    [
        ("plain", "plain"),
        ("org/project", "org_project"),
        ("org\\project", "org_project"),
        ("null\x00byte", "null_byte"),
        ("a/b\\c\x00d", "a_b_c_d"),
    ],
    ids=["plain", "slash", "backslash", "nul", "all_three"],
)
def test_cache_dir_for_project_sanitizes_path_separators(
    tmp_path: Path, project_name: str, expected_dir: str
) -> None:
    """Each of the three replacements is pinned by a name containing its char.

    No test called this helper at all, so every search/replacement literal was
    free: a project named ``ORG/NAME`` could have silently become a nested
    directory instead of a single sanitized one.
    """
    assert cache_dir_for_project(tmp_path, project_name) == tmp_path / expected_dir


def test_explicit_image_cache_entry_beats_the_cache_root(tmp_path: Path) -> None:
    """An ``image_cache`` entry is returned verbatim, root fallback untouched."""
    config_path = write_config_yaml(
        tmp_path / "custom.yaml",
        image_cache={"proj": "/explicit/dir"},
        cache={"images_root": "/fallback"},
    )

    assert resolve_images_cache_dir("proj", config_path) == Path("/explicit/dir")


def test_image_cache_falls_back_to_the_per_project_images_root(
    tmp_path: Path,
) -> None:
    """Without an ``image_cache`` entry the per-project root wins over the global.

    This is the only test that distinguishes ``for_project(name)`` from the
    global ``cache.images_root``, and the only one that reaches
    ``cache_dir_for_project`` from the resolution chain.
    """
    config_path = write_config_yaml(
        tmp_path / "custom.yaml",
        cache={
            "images_root": "/global",
            "projects": {"proj": {"images_root": "/per-project"}},
        },
    )

    assert resolve_images_cache_dir("proj", config_path) == Path("/per-project/proj")


def test_image_cache_unconfigured_project_resolves_to_none(tmp_path: Path) -> None:
    """Neither section configured — the caller must get None, not a bare root."""
    config_path = write_config_yaml(
        tmp_path / "custom.yaml", cvat={"host": "http://localhost:8080"}
    )

    assert resolve_images_cache_dir("proj", config_path) is None


# ---------------------------------------------------------------------------
# credential guard
# ---------------------------------------------------------------------------


def test_require_credentials_returns_self_when_both_are_set() -> None:
    """The happy path hands back the same config object."""
    cfg = CvatConfig(host="https://x.example", username="u", password="p")

    assert cfg.require_credentials() is cfg


@pytest.mark.parametrize(
    "cfg",
    [
        CvatConfig(username="u"),
        CvatConfig(password="p"),
        CvatConfig(),
    ],
    ids=["username_only", "password_only", "neither"],
)
def test_require_credentials_rejects_a_half_filled_pair(cfg: CvatConfig) -> None:
    """``username and password`` — an ``or`` here opens a broken CVAT session.

    Only the both-set case was covered before, so the guard could degrade to
    ``or`` and let a username-only config through to the SDK, where it fails
    much later and far less legibly.
    """
    with pytest.raises(MissingCredentialsError):
        cfg.require_credentials()


# ---------------------------------------------------------------------------
# the `upload` section: the only user of SectionConfig's base _to_raw
# ---------------------------------------------------------------------------


def test_upload_section_round_trips_non_default_values(tmp_path: Path) -> None:
    """``UploadConfig`` is the only section using the inherited ``_to_raw``.

    Nothing saved or loaded it, so the whole base serializer was unexecuted.
    """
    config_path = tmp_path / "custom.yaml"

    UploadConfig(images_per_job=25).save(config_path)

    reloaded = UploadConfig.load(config_path)
    assert reloaded.images_per_job == 25
    assert reloaded.image_quality == 100


@pytest.mark.parametrize(
    "section",
    [
        pytest.param({"images_per_job": 0}, id="zero-images-per-job"),
        pytest.param({"images_per_job": -5}, id="negative-images-per-job"),
        pytest.param({"image_quality": 101}, id="over-full-quality"),
        pytest.param({"image_quality": -1}, id="negative-quality"),
    ],
)
def test_unusable_upload_settings_are_rejected_at_load(
    tmp_path: Path, section: dict[str, int]
) -> None:
    """A bad value fails naming the setting, not deep inside the upload.

    ``images_per_job`` reaches CVAT as ``segment_size`` and divides the
    job-count estimate, so a hand-written ``0`` used to surface either as a
    CVAT rejection or as ``ZeroDivisionError`` — after the task had already
    been created. ``image_quality`` is the CVAT chunk quality, documented as
    0-100 by ``create_upload_task`` — so 0 stays legal and only the ends of
    that range are enforced.
    """
    config_path = write_config_yaml(tmp_path / "custom.yaml", upload=section)

    with pytest.raises(ValidationError):
        UploadConfig.load(config_path)


def test_saving_an_all_default_section_removes_it(tmp_path: Path) -> None:
    """An all-default section is dropped from the file, not written back.

    That is what ``exclude_defaults`` plus ``_dump() or None`` buy: without
    either, a wizard that touched nothing would still pin today's defaults
    into the user's config and freeze them across upgrades.
    """
    config_path = write_config_yaml(
        tmp_path / "custom.yaml",
        cvat={"host": "http://localhost:8080"},
        upload={"images_per_job": 7},
    )

    UploadConfig().save(config_path)

    assert yaml.safe_load(config_path.read_bytes()) == {
        "cvat": {"host": "http://localhost:8080"}
    }


def test_saving_an_all_default_section_absent_from_the_file_is_a_no_op(
    tmp_path: Path,
) -> None:
    """Removing a section that was never there must not raise.

    ``existing.pop(key, None)`` — the default is what makes this safe, and no
    earlier test removed a section from a file that did not contain it.
    """
    config_path = write_config_yaml(
        tmp_path / "custom.yaml", cvat={"host": "http://localhost:8080"}
    )

    UploadConfig().save(config_path)

    assert yaml.safe_load(config_path.read_bytes()) == {
        "cvat": {"host": "http://localhost:8080"}
    }

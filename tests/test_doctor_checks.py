"""Tests for individual check functions in cveta2/commands/doctor.py."""

import os
import pwd
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cveta2.adapters.config.settings import (
    CacheConfig,
    CacheProjectSettings,
    CvatConfig,
    ImageCacheConfig,
)
from cveta2.adapters.s3.diagnostics import check_aws_credentials
from cveta2.interfaces.commands.doctor import (
    _check_one,
    _log_broken_summary,
    _scan_permissions,
    check_cache_permissions,
    check_config,
    collect_cache_roots,
)

# ---------------------------------------------------------------------------
# check_config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cfg", "cache_dir", "expected"),
    [
        (CvatConfig(host="https://cvat.ai", username="u", password="p"), None, True),
        (CvatConfig(host="", username="u", password="p"), None, False),
        (CvatConfig(host="https://cvat.ai"), None, False),
        # A missing image cache directory only warns.
        (CvatConfig(host="https://cvat.ai", username="u", password="p"), "nope", True),
        (CvatConfig(host="https://cvat.ai", username="u", password="p"), "ok", True),
    ],
    ids=["env-fallback", "empty-host", "no-credentials", "bad-cache", "good-cache"],
)
def test_check_config(
    tmp_path: Path, cfg: CvatConfig, cache_dir: str | None, *, expected: bool
) -> None:
    (tmp_path / "ok").mkdir()
    ic_cfg = ImageCacheConfig(
        projects={"proj": tmp_path / cache_dir} if cache_dir else {}
    )
    with (
        patch(
            "cveta2.interfaces.commands.doctor.get_config_path",
            return_value=Path("/nonexistent"),
        ),
        patch(
            "cveta2.interfaces.commands.doctor.CvatConfig.from_env", return_value=cfg
        ),
        patch(
            "cveta2.adapters.config.settings.ImageCacheConfig.load",
            return_value=ic_cfg,
        ),
    ):
        assert check_config() is expected


# ---------------------------------------------------------------------------
# check_aws_credentials
# ---------------------------------------------------------------------------


def test_check_aws_no_boto3() -> None:
    import sys

    real_boto3 = sys.modules.get("boto3")
    sys.modules["boto3"] = None  # type: ignore[assignment]
    try:
        assert check_aws_credentials() is False
    finally:
        if real_boto3 is not None:
            sys.modules["boto3"] = real_boto3
        else:
            sys.modules.pop("boto3", None)


@pytest.mark.parametrize(
    ("access_key", "expected"),
    [(None, False), ("", False), ("AKIAIOSFODNN7EXAMPLE", True)],
    ids=["no-credentials", "empty-access-key", "valid"],
)
def test_check_aws_credentials(access_key: str | None, *, expected: bool) -> None:
    mock_session = MagicMock()
    mock_session.profile_name = "default"
    mock_session.region_name = "us-east-1"
    if access_key is None:
        mock_session.get_credentials.return_value = None
    else:
        creds = mock_session.get_credentials.return_value
        creds.get_frozen_credentials.return_value = SimpleNamespace(
            access_key=access_key
        )
    mock_boto3 = MagicMock()
    mock_boto3.Session.return_value = mock_session
    with patch.dict("sys.modules", {"boto3": mock_boto3}):
        assert check_aws_credentials() is expected


# ---------------------------------------------------------------------------
# _scan_permissions
# ---------------------------------------------------------------------------


def test_scan_permissions_reports_files_and_dirs(tmp_path: Path) -> None:
    f = tmp_path / "secret.jpg"
    f.write_text("data", encoding="utf-8")
    f.chmod(0o600)  # no group read
    d = tmp_path / "subdir"
    d.mkdir()
    d.chmod(0o740)  # group read but no group exec

    result = _scan_permissions(tmp_path)

    assert f in [p for p, _ in result.broken_files]
    assert d in [p for p, _ in result.broken_dirs]


def test_scan_permissions_fix_repairs_whole_tree(tmp_path: Path) -> None:
    sub = tmp_path / "project_1" / "images"
    sub.mkdir(parents=True)
    img = sub / "a.jpg"
    img.write_text("data", encoding="utf-8")
    img.chmod(0o600)
    sub.chmod(0o700)
    (tmp_path / "project_1").chmod(0o700)
    tmp_path.chmod(0o700)

    result = _scan_permissions(tmp_path, fix=True)

    assert result.broken_dirs == []
    assert result.broken_files == []
    assert result.fixed == 4
    assert stat.S_IMODE(sub.stat().st_mode) == 0o770
    assert stat.S_IMODE(img.stat().st_mode) == 0o660
    assert _scan_permissions(tmp_path).broken_dirs == []


@pytest.mark.skipif(os.getuid() == 0, reason="root ignores directory permissions")
def test_scan_permissions_unreadable_subdir_is_reported(
    tmp_path: Path, capture_logs: list[str]
) -> None:
    """A directory we cannot list is still named, and its subtree is flagged."""
    tmp_path.chmod(0o775)
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o000)
    try:
        result = _scan_permissions(tmp_path)
        broken_paths = [p for p, _ in result.broken_dirs]
        assert blocked in broken_paths
        assert any("blocked" in m for m in capture_logs)
    finally:
        blocked.chmod(0o700)


# ---------------------------------------------------------------------------
# collect_cache_roots
# ---------------------------------------------------------------------------


def _make_dirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def test_collect_cache_roots_covers_every_configured_location(tmp_path: Path) -> None:
    images = tmp_path / "images"
    tasks = tmp_path / "tasks"
    explicit = tmp_path / "explicit"
    per_project = tmp_path / "per-project"
    default_base = tmp_path / "xdg" / "cveta2"
    _make_dirs(images, tasks, explicit, per_project, default_base)

    with (
        patch(
            "cveta2.interfaces.commands.doctor.ImageCacheConfig.load",
            return_value=ImageCacheConfig(projects={"proj": explicit}),
        ),
        patch(
            "cveta2.interfaces.commands.doctor.CacheConfig.load",
            return_value=CacheConfig(
                images_root=images,
                tasks_root=tasks,
                projects={"other": CacheProjectSettings(images_root=per_project)},
            ),
        ),
        patch(
            "cveta2.interfaces.commands.doctor.default_cache_base",
            return_value=default_base,
        ),
    ):
        roots = collect_cache_roots()

    assert set(roots.values()) == {explicit, images, tasks, per_project, default_base}


def test_collect_cache_roots_skips_missing_and_nested(tmp_path: Path) -> None:
    images = tmp_path / "images"
    nested = images / "proj"
    _make_dirs(nested)

    with (
        patch(
            "cveta2.interfaces.commands.doctor.ImageCacheConfig.load",
            return_value=ImageCacheConfig(
                projects={"proj": nested, "gone": tmp_path / "nope"}
            ),
        ),
        patch(
            "cveta2.interfaces.commands.doctor.CacheConfig.load",
            return_value=CacheConfig(images_root=images),
        ),
        patch(
            "cveta2.interfaces.commands.doctor.default_cache_base",
            return_value=tmp_path / "missing-base",
        ),
    ):
        roots = collect_cache_roots()

    assert list(roots.values()) == [images]


# ---------------------------------------------------------------------------
# check_cache_permissions
# ---------------------------------------------------------------------------


def test_check_cache_permissions_no_roots_is_ok() -> None:
    with patch(
        "cveta2.interfaces.commands.doctor.collect_cache_roots", return_value={}
    ):
        assert check_cache_permissions() is True


def test_check_cache_permissions_fixes_owned_paths(tmp_path: Path) -> None:
    img = tmp_path / "a.jpg"
    img.write_text("data", encoding="utf-8")
    img.chmod(0o600)
    tmp_path.chmod(0o770)

    with patch(
        "cveta2.interfaces.commands.doctor.collect_cache_roots",
        return_value={"cache.images_root": tmp_path},
    ):
        assert check_cache_permissions(fix=True) is True

    assert stat.S_IMODE(img.stat().st_mode) == 0o660


def test_check_cache_permissions_lists_users_that_must_run_doctor(
    tmp_path: Path, capture_logs: list[str]
) -> None:
    """Paths owned by someone else are reported, naming every other owner.

    Creating a file owned by another user needs root, so the *current* user
    is made the foreign one by moving ``getuid`` away from the file's owner.
    """
    img = tmp_path / "a.jpg"
    img.write_text("data", encoding="utf-8")
    img.chmod(0o600)
    tmp_path.chmod(0o770)
    real_owner = pwd.getpwuid(os.getuid()).pw_name

    with (
        patch(
            "cveta2.interfaces.commands.doctor.collect_cache_roots",
            return_value={"cache.images_root": tmp_path},
        ),
        patch(
            "cveta2.interfaces.commands.doctor.os.getuid", return_value=os.getuid() + 1
        ),
    ):
        assert check_cache_permissions(fix=True) is False

    assert stat.S_IMODE(img.stat().st_mode) == 0o600
    assert any(real_owner in m and "doctor --cache" in m for m in capture_logs)


def test_check_cache_permissions_reports_own_unfixable_paths(
    tmp_path: Path, capture_logs: list[str]
) -> None:
    """A chmod that fails leaves the path broken instead of claiming success."""
    img = tmp_path / "a.jpg"
    img.write_text("data", encoding="utf-8")
    img.chmod(0o600)
    tmp_path.chmod(0o770)

    with (
        patch(
            "cveta2.interfaces.commands.doctor.collect_cache_roots",
            return_value={"cache.images_root": tmp_path},
        ),
        patch.object(Path, "chmod", side_effect=OSError("read-only file system")),
    ):
        assert check_cache_permissions(fix=True) is False

    assert any("read-only file system" in m for m in capture_logs)


# ---------------------------------------------------------------------------
# _check_one
# ---------------------------------------------------------------------------


def test_check_one_stat_failure_silently_skips() -> None:
    out: list[tuple[Path, str]] = []
    _check_one(Path("/nonexistent/path/file.txt"), is_dir=False, out=out)
    assert out == []


@pytest.mark.parametrize(
    ("is_dir", "mode", "broken"),
    [
        (False, 0o600, True),
        (False, 0o640, True),
        (False, 0o660, False),
        (True, 0o750, True),
        (True, 0o775, False),
    ],
)
def test_check_one_requires_group_access(
    tmp_path: Path, mode: int, *, is_dir: bool, broken: bool
) -> None:
    path = tmp_path / "entry"
    if is_dir:
        path.mkdir()
    else:
        path.write_text("x", encoding="utf-8")
    path.chmod(mode)
    out: list[tuple[Path, str]] = []
    _check_one(path, is_dir=is_dir, out=out)
    assert [p for p, _ in out] == ([path] if broken else [])


# ---------------------------------------------------------------------------
# _log_broken_summary
# ---------------------------------------------------------------------------


def test_log_broken_summary_counts_owners_and_truncates(
    tmp_path: Path, capture_logs: list[str]
) -> None:
    items: list[tuple[Path, str]] = []
    for i in range(15):
        f = tmp_path / f"f{i}.txt"
        f.write_text("x", encoding="utf-8")
        f.chmod(0o600)
        items.append((f, "bob"))

    _log_broken_summary("proj", tmp_path, [], items)

    assert any("15 file(s)" in m and "bob (15 items)" in m for m in capture_logs)
    assert any("… and 5 more" in m for m in capture_logs)


def test_aws_sdk_failure_is_translated_at_adapter_boundary() -> None:
    from botocore.exceptions import NoCredentialsError

    from cveta2.adapters.s3.diagnostics import check_aws_credentials
    from cveta2.domain.errors import Cveta2Error

    with (
        patch("boto3.Session", side_effect=NoCredentialsError()),
        pytest.raises(Cveta2Error, match="Unable to locate credentials"),
    ):
        check_aws_credentials()

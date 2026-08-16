"""Health checks for cveta2 configuration and caches.

Called by ``cveta2 doctor``.  All checks log their results via loguru
and return ``True`` when everything is fine.  With ``--cache`` the
permission check also repairs what the running user owns and names the
users who have to repair the rest themselves.
"""

from __future__ import annotations

import os
import pwd
import stat
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.config import (
    CacheConfig,
    CvatConfig,
    ImageCacheConfig,
    get_config_path,
)
from cveta2.fs_utils import default_cache_base
from cveta2.services.output import PREVIEW_LIMIT

if TYPE_CHECKING:
    import argparse


def run_doctor(args: argparse.Namespace | None = None) -> None:
    """Run all doctor checks and log a final summary."""
    fix_cache = args is not None and args.cache
    ok = True
    if not check_config():
        ok = False
    if not check_aws_credentials():
        ok = False
    if not check_cache_permissions(fix=fix_cache):
        ok = False

    if ok:
        logger.info("doctor: all checks passed")
    else:
        logger.warning("doctor: some checks failed (see messages above)")


def check_config() -> bool:
    """Validate that the user config is correct.

    Returns ``True`` when everything looks good.
    """
    logger.info("doctor: checking configuration …")

    config_path = get_config_path()

    # --- Config file existence ---
    if not config_path.is_file():
        logger.warning(
            f"Config file not found: {config_path}. "
            "Run 'cveta2 setup' or set env variables."
        )
        cfg = CvatConfig.from_env()
    else:
        logger.info(f"Config file: {config_path}")
        cfg = CvatConfig.load()

    problems: list[str] = []

    if not cfg.host:
        problems.append(
            "'host' is not configured (set CVAT_HOST or cvat.host in config)"
        )

    has_password = bool(cfg.username and cfg.password)
    if not has_password:
        problems.append("No credentials: provide CVAT_USERNAME + CVAT_PASSWORD")

    ic_cfg = ImageCacheConfig.load()
    if not ic_cfg.projects:
        logger.info("image_cache: no projects configured (optional)")
    else:
        for proj_name, proj_dir in ic_cfg.projects.items():
            if not proj_dir.is_dir():
                problems.append(
                    f"image_cache.{proj_name}: directory does not exist: {proj_dir}"
                )
            else:
                logger.info(f"image_cache.{proj_name}: {proj_dir} — OK")

    if problems:
        for p in problems:
            logger.error(f"config: {p}")
        return False

    logger.info("Config: OK")
    return True


def check_aws_credentials() -> bool:
    """Check that AWS/S3 credentials are resolvable by boto3.

    Returns ``True`` when credentials are found.
    """
    logger.info("doctor: checking AWS credentials …")

    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        logger.error("AWS: boto3 is not installed — S3 operations will fail")
        return False

    session = boto3.Session()
    creds = session.get_credentials()

    if creds is None:
        logger.error(
            "AWS: no credentials found. "
            "Configure via AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars, "
            "~/.aws/credentials, or an IAM role."
        )
        return False

    resolved = creds.get_frozen_credentials()
    if not resolved.access_key:
        logger.error(
            "AWS: credentials found but access key is empty. "
            "Check your ~/.aws/credentials or env vars."
        )
        return False

    # Show which credential source is active (without leaking secrets)
    key_preview = resolved.access_key[:4] + "…" + resolved.access_key[-4:]
    profile = session.profile_name or "(default)"
    region = session.region_name or "(not set)"
    logger.info(
        f"AWS: credentials OK — "
        f"profile={profile}, region={region}, access_key={key_preview}"
    )
    return True


def collect_cache_roots(config_path: Path | None = None) -> dict[str, Path]:
    """Return every cache directory tree cveta2 may write, keyed by its label.

    Covers the explicit ``image_cache`` project dirs, the ``cache``
    section's global and per-project roots, and cveta2's own cache base
    (task annotations plus unfinished upload manifests).  Config files
    are not caches and are left out: they are per-user by design.

    Roots that do not exist are dropped, and a root nested inside
    another one is dropped too — the outer walk already covers it.
    """
    labelled: dict[str, Path] = {
        f"image_cache.{name}": path
        for name, path in ImageCacheConfig.load(config_path).projects.items()
    }
    cache_cfg = CacheConfig.load(config_path)
    if cache_cfg.images_root is not None:
        labelled["cache.images_root"] = cache_cfg.images_root
    if cache_cfg.tasks_root is not None:
        labelled["cache.tasks_root"] = cache_cfg.tasks_root
    for name, settings in cache_cfg.projects.items():
        if settings.images_root is not None:
            labelled[f"cache.projects.{name}.images_root"] = settings.images_root
        if settings.tasks_root is not None:
            labelled[f"cache.projects.{name}.tasks_root"] = settings.tasks_root
    labelled["cache_dir"] = default_cache_base()

    existing = [
        (label, path.resolve()) for label, path in labelled.items() if path.is_dir()
    ]
    existing.sort(key=lambda item: len(item[1].parts))
    roots: dict[str, Path] = {}
    for label, path in existing:
        if any(path == kept or kept in path.parents for kept in roots.values()):
            continue
        roots[label] = path
    return roots


def check_cache_permissions(*, fix: bool = False) -> bool:
    """Check that cache entries are group-accessible; with *fix*, repair them.

    Files must have group read+write; directories must have group
    read+write+execute so that all users in the same group can use and
    update the cache.  ``chmod`` only works for the owner, so *fix*
    repairs the running user's own entries and the rest are reported
    together with the users who must run the fix themselves.

    Returns ``True`` when nothing is left broken.
    """
    roots = collect_cache_roots()
    if not roots:
        logger.info("doctor: no cache directories to check permissions for")
        return True

    logger.info(
        f"doctor: {'fixing' if fix else 'checking'} cache group permissions in "
        f"{len(roots)} location(s) …"
    )
    unfixed: Counter[str] = Counter()

    for label, root in roots.items():
        result = _scan_permissions(root, fix=fix)
        if result.fixed:
            logger.info(
                f"{label} ({root}): granted group access to {result.fixed} path(s)"
            )
        broken = result.broken
        if broken:
            unfixed.update(owner for _, owner in broken)
            _log_broken_summary(label, root, result.broken_dirs, result.broken_files)
        elif not result.fixed:
            logger.info(f"{label} ({root}): group permissions OK")

    if not unfixed:
        return True
    _log_users_to_notify(unfixed, fix=fix)
    return False


_BrokenList = list[tuple[Path, str]]


@dataclass
class _ScanResult:
    """Outcome of one walk: what stayed broken and how much was repaired."""

    broken_dirs: _BrokenList = field(default_factory=list)
    broken_files: _BrokenList = field(default_factory=list)
    fixed: int = 0

    @property
    def broken(self) -> _BrokenList:
        """Every still-broken entry, directories first."""
        return self.broken_dirs + self.broken_files


def _scan_permissions(root_dir: Path, *, fix: bool = False) -> _ScanResult:
    """Walk *root_dir* checking group access, repairing owned paths when *fix*."""
    result = _ScanResult()

    def record_unreadable(error: OSError) -> None:
        logger.warning(
            f"doctor: не удалось прочитать {error.filename} ({error}) — "
            f"содержимое каталога не проверено"
        )
        if error.filename is not None:
            _check_one(
                Path(error.filename), is_dir=True, out=result.broken_dirs, fix=fix
            )

    for root, _dirs, files in os.walk(root_dir, onerror=record_unreadable):
        root_path = Path(root)
        result.fixed += _check_one(
            root_path, is_dir=True, out=result.broken_dirs, fix=fix
        )
        for fname in files:
            result.fixed += _check_one(
                root_path / fname, is_dir=False, out=result.broken_files, fix=fix
            )

    return result


def _check_one(
    path: Path, *, is_dir: bool, out: _BrokenList, fix: bool = False
) -> bool:
    """Grant group access to *path* when asked and allowed; else record it.

    Returns ``True`` when the path was repaired.  A path that already
    has the required bits is neither repaired nor recorded.
    """
    try:
        st = path.stat()
    except OSError as e:
        logger.debug(f"Не удалось проверить {path}: {e}")
        return False

    need = (
        (stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP)
        if is_dir
        else (stat.S_IRGRP | stat.S_IWGRP)
    )
    if (st.st_mode & need) == need:
        return False

    if (
        fix
        and st.st_uid == os.getuid()
        and _grant_group_access(path, st.st_mode | need)
    ):
        return True

    out.append((path, _owner_name(st.st_uid)))
    return False


def _grant_group_access(path: Path, mode: int) -> bool:
    """Add the missing group bits to *path*; report failure instead of raising."""
    try:
        path.chmod(stat.S_IMODE(mode))
    except OSError as e:
        logger.warning(f"doctor: не удалось выставить права на {path}: {e}")
        return False
    logger.debug(f"doctor: права {oct(stat.S_IMODE(mode))} выставлены на {path}")
    return True


def _owner_name(uid: int) -> str:
    """Return the login name for *uid*, falling back to the bare number."""
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _log_broken_summary(
    label: str,
    root_dir: Path,
    broken_dirs: _BrokenList,
    broken_files: _BrokenList,
) -> None:
    """Log a compact summary of permission problems for one cache root."""
    owner_counts = Counter(owner for _, owner in broken_dirs + broken_files)
    owners_str = ", ".join(
        f"{owner} ({cnt} items)" for owner, cnt in owner_counts.items()
    )

    logger.warning(
        f"{label} ({root_dir}): "
        f"{len(broken_dirs)} dir(s) and {len(broken_files)} file(s) "
        f"not group-accessible. Owners: {owners_str}"
    )

    examples = (broken_dirs + broken_files)[:PREVIEW_LIMIT]
    for path, owner in examples:
        mode_str = stat.filemode(path.stat().st_mode)
        logger.warning(f"  {mode_str}  {owner}  {path}")

    remaining = len(broken_dirs) + len(broken_files) - len(examples)
    if remaining > 0:
        logger.warning(f"  … and {remaining} more")


def _log_users_to_notify(unfixed: Counter[str], *, fix: bool) -> None:
    """Name the users who have to run the fix on their own files."""
    me = _owner_name(os.getuid())
    mine = unfixed.pop(me, 0)
    if mine and fix:
        logger.warning(
            f"{mine} path(s) you own could not be repaired — see the errors above"
        )
    elif mine:
        logger.warning(
            f"{mine} path(s) you own can be repaired here: run 'cveta2 doctor --cache'"
        )
    if not unfixed:
        return
    owners_str = ", ".join(
        f"{owner} ({cnt} items)" for owner, cnt in sorted(unfixed.items())
    )
    logger.warning(
        f"These users own the remaining paths and must run "
        f"'cveta2 doctor --cache' themselves: {owners_str}"
    )

"""Health checks for cveta2 configuration and image cache.

Called by ``cveta2 doctor``.  All checks log their results via loguru
and return ``True`` when everything is fine.
"""

from __future__ import annotations

import os
import pwd
import stat
from pathlib import Path

from loguru import logger

from cveta2.config import CONFIG_PATH, CvatConfig, load_image_cache_config


def run_doctor() -> None:
    """Run all doctor checks and log a final summary."""
    ok = True
    if not check_config():
        ok = False
    if not check_aws_credentials():
        ok = False
    if not check_cache_permissions():
        ok = False

    if ok:
        logger.info("doctor: all checks passed")
    else:
        logger.warning("doctor: some checks failed (see messages above)")


# ------------------------------------------------------------------
# 1. Config validation
# ------------------------------------------------------------------


def check_config() -> bool:
    """Validate that the user config is correct.

    Returns ``True`` when everything looks good.
    """
    logger.info("doctor: checking configuration …")

    config_path = Path(os.environ.get("CVETA2_CONFIG", str(CONFIG_PATH)))

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

    has_token = bool(cfg.token)
    has_password = bool(cfg.username and cfg.password)
    if not has_token and not has_password:
        problems.append(
            "No credentials: provide CVAT_TOKEN or CVAT_USERNAME + CVAT_PASSWORD"
        )

    ic_cfg = load_image_cache_config()
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


# ------------------------------------------------------------------
# 2. AWS credentials
# ------------------------------------------------------------------


def check_aws_credentials() -> bool:
    """Check that AWS/S3 credentials are resolvable by boto3.

    Returns ``True`` when credentials are found.
    """
    logger.info("doctor: checking AWS credentials …")

    try:
        import boto3  # noqa: PLC0415
        import botocore.exceptions  # noqa: PLC0415, F401
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


# ------------------------------------------------------------------
# 3. Cache group-permission check
# ------------------------------------------------------------------

_MAX_EXAMPLES = 10


def check_cache_permissions() -> bool:
    """Check that images in cache dirs are group-accessible.

    Files must have group-read; directories must have group-read +
    group-execute so that all users in the same group can use the cache.

    Returns ``True`` when everything is fine.
    """
    ic_cfg = load_image_cache_config()
    if not ic_cfg.projects:
        logger.info("doctor: no image_cache directories to check permissions for")
        return True

    logger.info("doctor: checking image cache group permissions …")
    all_ok = True

    for proj_name, proj_dir in ic_cfg.projects.items():
        if not proj_dir.is_dir():
            continue  # already reported in check_config

        broken_dirs, broken_files = _scan_permissions(proj_dir)

        if broken_dirs or broken_files:
            all_ok = False
            _log_broken_summary(proj_name, proj_dir, broken_dirs, broken_files)
        else:
            logger.info(f"image_cache.{proj_name} ({proj_dir}): group permissions OK")

    return all_ok


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

_BrokenList = list[tuple[Path, str]]


def _scan_permissions(root_dir: Path) -> tuple[_BrokenList, _BrokenList]:
    """Walk *root_dir* and return (broken_dirs, broken_files)."""
    broken_dirs: _BrokenList = []
    broken_files: _BrokenList = []

    for root, _dirs, files in os.walk(root_dir):
        root_path = Path(root)
        _check_one(root_path, is_dir=True, out=broken_dirs)
        for fname in files:
            _check_one(root_path / fname, is_dir=False, out=broken_files)

    return broken_dirs, broken_files


def _check_one(path: Path, *, is_dir: bool, out: _BrokenList) -> None:
    """Append *path* to *out* if required group bits are missing."""
    try:
        st = path.stat()
    except OSError:
        return

    need = (stat.S_IRGRP | stat.S_IXGRP) if is_dir else stat.S_IRGRP
    if (st.st_mode & need) != need:
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        out.append((path, owner))


def _log_broken_summary(
    proj_name: str,
    proj_dir: Path,
    broken_dirs: _BrokenList,
    broken_files: _BrokenList,
) -> None:
    """Log a compact summary of permission problems for one project."""
    owner_counts: dict[str, int] = {}
    for _, owner in broken_dirs + broken_files:
        owner_counts[owner] = owner_counts.get(owner, 0) + 1

    owners_str = ", ".join(
        f"{owner} ({cnt} items)" for owner, cnt in owner_counts.items()
    )

    logger.warning(
        f"image_cache.{proj_name} ({proj_dir}): "
        f"{len(broken_dirs)} dir(s) and {len(broken_files)} file(s) "
        f"not group-accessible. Owners: {owners_str}"
    )

    examples = (broken_dirs + broken_files)[:_MAX_EXAMPLES]
    for path, owner in examples:
        mode_str = stat.filemode(path.stat().st_mode)
        logger.warning(f"  {mode_str}  {owner}  {path}")

    remaining = len(broken_dirs) + len(broken_files) - len(examples)
    if remaining > 0:
        logger.warning(f"  … and {remaining} more")

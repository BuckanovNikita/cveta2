"""AWS credential inspection and SDK error translation."""

from botocore.exceptions import BotoCoreError
from loguru import logger

from cveta2.domain.errors import Cveta2Error


def _check_aws_credentials() -> "bool":
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


def check_aws_credentials() -> bool:
    """Report credential availability, translating SDK failures at this boundary."""
    try:
        return _check_aws_credentials()
    except BotoCoreError as error:
        raise Cveta2Error(str(error)) from error

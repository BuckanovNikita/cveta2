"""Diagnostic adapters available to command entry points."""

from cveta2.adapters.s3.diagnostics import check_aws_credentials

__all__ = ["check_aws_credentials"]

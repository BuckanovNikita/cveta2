"""Shared argument declarations for the incoming CLI command families."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

_PROJECT_HELP = (
    "Project ID or name, optionally prefixed with an organization: "
    "ORG/PROJECT (default org comes from config; /PROJECT selects the "
    "personal workspace). If omitted, interactive project selection is shown."
)


def add_project_arg(
    parser: "argparse.ArgumentParser",
    help_text: str = _PROJECT_HELP,
) -> None:
    """Add the shared ``--project`` argument."""
    parser.add_argument("--project", "-p", type=str, default=None, help=help_text)


def add_config_arg(parser: "argparse.ArgumentParser") -> None:
    """Add the shared ``--config`` argument."""
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to YAML config (default: ~/.config/cveta2/config.yaml "
            "or CVETA2_CONFIG)."
        ),
    )


def add_list_arg(parser: "argparse.ArgumentParser", help_text: str) -> None:
    """Add the shared ``--list`` argument."""
    parser.add_argument("--list", dest="list_only", action="store_true", help=help_text)

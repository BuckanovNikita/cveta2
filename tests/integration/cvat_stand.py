#!/usr/bin/env python3
"""Inspect and clean this project's objects on the cluster CVAT stand.

    uv run python tests/integration/cvat_stand.py verify
    uv run python tests/integration/cvat_stand.py ls
    uv run python tests/integration/cvat_stand.py cleanup --tag <run-tag> [--dry-run]

Credentials come from ``CVAT_INTEGRATION_HOST`` / ``CVAT_INTEGRATION_USER`` /
``CVAT_INTEGRATION_PASSWORD`` / ``CVAT_INTEGRATION_ORG``, which
``scripts/integration_env.sh`` derives from the project's Secret through the
k8s-infra skill (``cvat.py --project cveta2 env``).

``verify`` logs in as that user, checks that the stand answers as the same
account and that the account is a member of the organization, and fails with
the exact missing piece otherwise. It never registers users or organizations:
the stand admin creates both with ``deploy_cvat.sh`` (k8s-infra). The login
runs without the organization header, which CVAT rejects for a slug the user
is not a member of - the very state ``verify`` reports.

``ls`` and ``cleanup`` see only objects owned by the integration user; the
organization is shared with other projects. ``cleanup --tag`` matches
``"<tag> "`` - the tag followed by a space - so that tag ``nkt`` never matches
``nkt-feature coco8-dev``. Do not "simplify" it to a bare prefix. Projects go
first (their tasks cascade), then standalone tasks, then cloud storages, which
nothing may reference any more. Stale objects of dead runs belong to the
skill's ``cvat.py cleanup --stale`` and the janitor, not to this script.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from cvat_sdk.api_client.exceptions import ApiException
from cvat_sdk.core.client import Client
from loguru import logger
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

PAGE_SIZE = 100
SECRET_HINT = (
    "the credentials are the cveta2 Secret on the cluster "
    "(`cvat.py --project cveta2 env` from the k8s-infra skill); "
    "the stand admin fixes the account with deploy_cvat.sh"
)


class StandError(RuntimeError):
    """A state the scripts must not paper over."""


class StandSettings(BaseModel):
    host: str
    username: str
    password: str
    organization: str

    @classmethod
    def from_env(cls) -> StandSettings:
        keys = {
            "host": "CVAT_INTEGRATION_HOST",
            "username": "CVAT_INTEGRATION_USER",
            "password": "CVAT_INTEGRATION_PASSWORD",
            "organization": "CVAT_INTEGRATION_ORG",
        }
        values = {field: os.environ.get(env, "").strip() for field, env in keys.items()}
        missing = [keys[field] for field, value in values.items() if not value]
        if missing:
            raise StandError(
                f"{', '.join(missing)} not set; source scripts/integration_env.sh "
                "(it exports them from the cveta2 Secret through the k8s-infra skill)"
            )
        values["host"] = values["host"].rstrip("/")
        return cls(**values)


class Listing(BaseModel):
    """One deletable object, uniformly named whatever the SDK calls it."""

    kind: str
    id: int
    name: str
    owner: str
    created: datetime
    project_id: int | None = None

    def age(self) -> str:
        delta = datetime.now(timezone.utc) - self.created
        hours = int(delta.total_seconds() // 3600)
        if hours >= 24:
            return f"{hours // 24}d{hours % 24}h"
        return f"{hours}h{int(delta.total_seconds() % 3600 // 60)}m"


def _owner_name(item: object) -> str:
    # getattr: the SDK's generated models are opaque, and owner is optional on all three
    owner = getattr(item, "owner", None)
    return str(owner.username) if owner is not None else "-"


def _login(settings: StandSettings) -> Client:
    """Open a client with one anonymous request (the login), not two.

    The stand throttles anonymous requests per client IP, and the server
    version check every ``make_client`` performs is one of them.
    """
    client = Client(settings.host, check_server_version=False)
    try:
        client.login((settings.username, settings.password))
    except ApiException as exc:
        client.close()
        raise StandError(
            f"login as '{settings.username}' at {settings.host} failed: "
            f"{exc.status} {exc.body}; {SECRET_HINT}"
        ) from exc
    return client


def _list_pages(fetch: Callable[[int], object]) -> Iterator[object]:
    page = 1
    while True:
        result = fetch(page)
        yield from result.results  # type: ignore[attr-defined]
        if not result.next:  # type: ignore[attr-defined]
            return
        page += 1


def _member_organization_slugs(client: Client) -> set[str]:
    api = client.api_client.organizations_api
    organizations = _list_pages(
        lambda page: api.list(page=page, page_size=PAGE_SIZE)[0]
    )
    return {str(org.slug) for org in organizations}  # type: ignore[attr-defined]


def _verify_identity(client: Client, settings: StandSettings) -> None:
    """Fail with the one thing that is wrong: the account, or its membership."""
    try:
        me = client.api_client.users_api.retrieve_self()[0]
        slugs = _member_organization_slugs(client)
    except ApiException as exc:
        raise StandError(
            f"{settings.host} rejected the logged-in user '{settings.username}': "
            f"{exc.status} {exc.body}; {SECRET_HINT}"
        ) from exc
    if str(me.username) != settings.username:
        raise StandError(
            f"logged in as '{me.username}' but CVAT_INTEGRATION_USER is "
            f"'{settings.username}'; the Secret and the environment disagree, "
            f"{SECRET_HINT}"
        )
    if settings.organization not in slugs:
        member_of = ", ".join(sorted(slugs)) or "no organization"
        raise StandError(
            f"user '{settings.username}' is not a member of organization "
            f"'{settings.organization}' on {settings.host} (member of: {member_of}); "
            f"this script never creates memberships, {SECRET_HINT}"
        )


def open_stand() -> tuple[Client, StandSettings]:
    """Return an authenticated client scoped to the integration organization."""
    settings = StandSettings.from_env()
    client = _login(settings)
    client.organization_slug = settings.organization
    return client, settings


def _owned_by(settings: StandSettings) -> Callable[[Listing], bool]:
    return lambda item: item.owner == settings.username


def list_projects(client: Client) -> list[Listing]:
    return [
        Listing(
            kind="project",
            id=int(project.id),
            name=str(project.name),
            owner=_owner_name(project),
            created=project.created_date,
        )
        for project in client.projects.list()
    ]


def list_tasks(client: Client) -> list[Listing]:
    return [
        Listing(
            kind="task",
            id=int(task.id),
            name=str(task.name),
            owner=_owner_name(task),
            created=task.created_date,
            project_id=int(task.project_id) if task.project_id is not None else None,
        )
        for task in client.tasks.list()
    ]


def list_cloud_storages(client: Client) -> list[Listing]:
    api = client.api_client.cloudstorages_api
    return [
        Listing(
            kind="storage",
            id=int(storage.id),  # type: ignore[attr-defined]
            name=str(storage.display_name),  # type: ignore[attr-defined]
            owner=_owner_name(storage),
            created=storage.created_date,  # type: ignore[attr-defined]
        )
        for storage in _list_pages(
            lambda page: api.list(page=page, page_size=PAGE_SIZE)[0]
        )
    ]


def cmd_verify(_: argparse.Namespace) -> int:
    settings = StandSettings.from_env()
    client = _login(settings)
    try:
        _verify_identity(client, settings)
        client.organization_slug = settings.organization
        about = client.api_client.server_api.retrieve_about()[0]
    finally:
        client.close()
    logger.info(
        f"Stand ready: CVAT {about.version} at {settings.host}, "
        f"user '{settings.username}' is a member of organization "
        f"'{settings.organization}'"
    )
    return 0


def cmd_ls(_: argparse.Namespace) -> int:
    client, settings = open_stand()
    owned = _owned_by(settings)
    try:
        projects = [p for p in list_projects(client) if owned(p)]
        tasks = [t for t in list_tasks(client) if owned(t)]
        storages = [s for s in list_cloud_storages(client) if owned(s)]
    finally:
        client.close()
    logger.info(
        f"organization {settings.organization}, owner {settings.username}: "
        f"{len(projects)} project(s), {len(tasks)} task(s), "
        f"{len(storages)} cloud storage(s)"
    )
    for item in sorted(projects + storages, key=lambda i: i.created):
        logger.info(f"{item.kind:<8}{item.id:>6}  {item.age():>7}  {item.name}")
    for task in sorted(tasks, key=lambda i: i.created):
        where = f"in project {task.project_id}" if task.project_id else "standalone"
        logger.info(
            f"{task.kind:<8}{task.id:>6}  {task.age():>7}  {task.name}  ({where})"
        )
    return 0


def _tagged_and_owned(tag: str, settings: StandSettings) -> Callable[[Listing], bool]:
    prefix = f"{tag} "
    owned = _owned_by(settings)
    return lambda item: item.name.startswith(prefix) and owned(item)


def _doomed(client: Client, selected: Callable[[Listing], bool]) -> list[Listing]:
    projects = [p for p in list_projects(client) if selected(p)]
    doomed_project_ids = {p.id for p in projects}
    tasks = [
        t
        for t in list_tasks(client)
        if selected(t) and t.project_id not in doomed_project_ids
    ]
    storages = [s for s in list_cloud_storages(client) if selected(s)]
    return projects + tasks + storages


def _destroy(client: Client, item: Listing) -> None:
    api = client.api_client
    destroy = {
        "project": api.projects_api.destroy,
        "task": api.tasks_api.destroy,
        "storage": api.cloudstorages_api.destroy,
    }[item.kind]
    destroy(item.id)


def cmd_cleanup(args: argparse.Namespace) -> int:
    client, settings = open_stand()
    selected = _tagged_and_owned(args.tag, settings)
    try:
        items = _doomed(client, selected)
        if not items:
            logger.info(
                f"nothing of '{args.tag}' owned by {settings.username} in "
                f"organization {settings.organization}"
            )
            return 0
        verb = "would delete" if args.dry_run else "deleting"
        for item in items:
            logger.info(f"{verb} {item.kind} {item.id} '{item.name}'")
            if not args.dry_run:
                _destroy(client, item)
        if args.dry_run:
            return 0
        remaining = _doomed(client, selected)
    finally:
        client.close()
    if remaining:
        names = ", ".join(f"{i.kind} {i.id} '{i.name}'" for i in remaining)
        raise StandError(f"cleanup left {len(remaining)} item(s) behind: {names}")
    logger.info(
        f"deleted {len(items)} item(s) from organization {settings.organization}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify",
        help="log in as the integration user and prove its organization membership",
    )
    verify.set_defaults(run=cmd_verify)
    ls = commands.add_parser(
        "ls", help="projects, tasks and cloud storages the integration user owns"
    )
    ls.set_defaults(run=cmd_ls)
    cleanup = commands.add_parser(
        "cleanup", help="delete one run's objects owned by the integration user"
    )
    cleanup.add_argument(
        "--tag", required=True, help="delete objects named '<tag> ...' (this run's)"
    )
    cleanup.add_argument("--dry-run", action="store_true", help="list without deleting")
    cleanup.set_defaults(run=cmd_cleanup)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.run(args))
    except StandError as error:
        logger.error(str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())

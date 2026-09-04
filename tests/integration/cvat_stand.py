#!/usr/bin/env python3
"""Manage the integration account and organization on the cluster CVAT stand.

    uv run python tests/integration/cvat_stand.py bootstrap
    uv run python tests/integration/cvat_stand.py ls
    uv run python tests/integration/cvat_stand.py cleanup --tag <run-tag> [--dry-run]
    uv run python tests/integration/cvat_stand.py cleanup --stale <hours> [--dry-run]

Credentials come from ``CVAT_INTEGRATION_HOST`` / ``CVAT_INTEGRATION_USER`` /
``CVAT_INTEGRATION_PASSWORD`` / ``CVAT_INTEGRATION_ORG``, which
``scripts/integration_env.sh`` exports from ``tests/integration/.env``.

``bootstrap`` registers the account when it does not exist yet, creates the
organization when the account is not a member of one with that slug, and
fails loudly on every other state (wrong password, slug owned by someone
else). It runs without the organization header until the organization is
known to exist: CVAT rejects every request, login included, whose
``X-Organization`` names a missing slug.

``cleanup --tag`` matches ``"<tag> "`` - the tag followed by a space - so that
tag ``nkt`` never matches ``nkt-feature coco8-dev``. Do not "simplify" it to
a bare prefix. Projects go first (their tasks cascade), then standalone
tasks, then cloud storages, which nothing may reference any more.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from cvat_sdk.api_client import models as cvat_models
from cvat_sdk.api_client.exceptions import ApiException
from cvat_sdk.core.client import Client
from loguru import logger
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

PAGE_SIZE = 100
REGISTER_EMAIL_DOMAIN = "cveta2.local"


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
                "(it reads tests/integration/.env, see .env.example)"
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
    except ApiException:
        client.close()
        raise
    return client


def _register(settings: StandSettings) -> None:
    client = Client(settings.host, check_server_version=False)
    request = cvat_models.RegisterSerializerExRequest(
        username=settings.username,
        password1=settings.password,
        password2=settings.password,
        email=f"{settings.username}@{REGISTER_EMAIL_DOMAIN}",
        first_name="cveta2",
        last_name="integration",
    )
    try:
        client.api_client.auth_api.create_register(request)
    except ApiException as exc:
        raise StandError(
            f"cannot register user '{settings.username}' on {settings.host}: "
            f"{exc.status} {exc.body}"
        ) from exc
    finally:
        client.close()
    logger.info(f"Registered user '{settings.username}' on {settings.host}")


def _connect(settings: StandSettings, *, register_if_missing: bool) -> Client:
    """Log in; on a rejected login optionally register the user and retry once."""
    try:
        return _login(settings)
    except ApiException as exc:
        if exc.status not in (400, 401, 403) or not register_if_missing:
            raise StandError(
                f"login as '{settings.username}' at {settings.host} failed: "
                f"{exc.status} {exc.body}"
            ) from exc
    _register(settings)
    try:
        return _login(settings)
    except ApiException as exc:
        raise StandError(
            f"user '{settings.username}' exists on {settings.host} but "
            "CVAT_INTEGRATION_PASSWORD is not its password"
        ) from exc


def _list_pages(fetch: Callable[[int], object]) -> Iterator[object]:
    page = 1
    while True:
        result = fetch(page)
        yield from result.results  # type: ignore[attr-defined]
        if not result.next:  # type: ignore[attr-defined]
            return
        page += 1


def _member_organizations(client: Client) -> list[object]:
    api = client.api_client.organizations_api
    return list(_list_pages(lambda page: api.list(page=page, page_size=PAGE_SIZE)[0]))


def _ensure_organization(client: Client, settings: StandSettings) -> None:
    slugs = {str(org.slug) for org in _member_organizations(client)}  # type: ignore[attr-defined]
    if settings.organization in slugs:
        logger.info(f"Organization '{settings.organization}': present")
        return
    request = cvat_models.OrganizationWriteRequest(
        slug=settings.organization, name="cveta2 integration tests"
    )
    try:
        client.api_client.organizations_api.create(request)
    except ApiException as exc:
        raise StandError(
            f"cannot create organization '{settings.organization}': "
            f"{exc.status} {exc.body}. If the slug already exists, another account "
            "owns it; pick a different CVAT_INTEGRATION_ORG or have its owner add "
            "this user"
        ) from exc
    logger.info(f"Organization '{settings.organization}': created")


def open_stand(*, register_if_missing: bool = False) -> tuple[Client, StandSettings]:
    """Return an authenticated client scoped to the integration organization."""
    settings = StandSettings.from_env()
    client = _connect(settings, register_if_missing=register_if_missing)
    if register_if_missing:
        _ensure_organization(client, settings)
    client.organization_slug = settings.organization
    return client, settings


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


def cmd_bootstrap(_: argparse.Namespace) -> int:
    client, settings = open_stand(register_if_missing=True)
    try:
        about = client.api_client.server_api.retrieve_about()[0]
        me = client.api_client.users_api.retrieve_self()[0]
    finally:
        client.close()
    logger.info(
        f"Stand ready: CVAT {about.version} at {settings.host}, "
        f"user '{me.username}' (id {me.id}), "
        f"organization '{settings.organization}'"
    )
    return 0


def cmd_ls(_: argparse.Namespace) -> int:
    client, settings = open_stand()
    try:
        projects = list_projects(client)
        tasks = list_tasks(client)
        storages = list_cloud_storages(client)
    finally:
        client.close()
    logger.info(
        f"organization {settings.organization}: {len(projects)} project(s), "
        f"{len(tasks)} task(s), {len(storages)} cloud storage(s)"
    )
    for item in sorted(projects + storages, key=lambda i: i.created):
        logger.info(
            f"{item.kind:<8}{item.id:>6}  {item.age():>7}  {item.owner:<12} {item.name}"
        )
    for task in sorted(tasks, key=lambda i: i.created):
        where = f"in project {task.project_id}" if task.project_id else "standalone"
        logger.info(
            f"{task.kind:<8}{task.id:>6}  {task.age():>7}  {task.owner:<12} "
            f"{task.name}  ({where})"
        )
    return 0


def _selector(args: argparse.Namespace) -> Callable[[Listing], bool]:
    if args.tag:
        prefix = f"{args.tag} "
        return lambda item: item.name.startswith(prefix)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.stale)
    return lambda item: item.created < cutoff


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
    if bool(args.tag) == (args.stale is not None):
        raise StandError(
            "cleanup needs exactly one of --tag <run-tag> or --stale <hours>"
        )
    selected = _selector(args)
    client, settings = open_stand()
    try:
        items = _doomed(client, selected)
        if not items:
            logger.info(f"nothing to clean in organization {settings.organization}")
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
    bootstrap = commands.add_parser(
        "bootstrap",
        help="register the account and organization if missing; prove the stand is up",
    )
    bootstrap.set_defaults(run=cmd_bootstrap)
    ls = commands.add_parser(
        "ls", help="projects, tasks and cloud storages in the organization"
    )
    ls.set_defaults(run=cmd_ls)
    cleanup = commands.add_parser("cleanup", help="delete objects in the organization")
    cleanup.add_argument("--tag", help="delete objects named '<tag> ...' (this run's)")
    cleanup.add_argument(
        "--stale", type=float, help="delete objects older than N hours"
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

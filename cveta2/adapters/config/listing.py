"""The effective configuration as ``cveta2 setup --list`` shows it, with the origin of each value.

Read-only: the files are read as written, never through a writer and never
repaired. The effective loaders are not used either, since they refuse a
personal file whose overrides the global file does not allow; the listing has
to work in that state, so it applies the overrides itself and shows refused
ones as not applied.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from cveta2.adapters.config.project import (
    find_project_key,
    optional_global_config,
    project_config_path,
    read_config,
    read_local_overrides,
)
from cveta2.adapters.config.settings import (
    CacheConfig,
    ImageCacheConfig,
    NetworkConfig,
    UploadConfig,
    _load_preset_data,
    _parse_int_env,
    _parse_timeout_env,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.managed.models import ProjectConfig, hide_url_userinfo
from cveta2.domain.managed.overrides import LocalOverrides, apply_local_overrides, override_leaves

type ValueOrigin = Literal["default", "personal", "global", "override", "environment"]

_HIDDEN = "***"
_PROJECT_FIELDS = ("id", "sync_root", "ignored_prefix", "task_cache_s3")


@dataclass(frozen=True)
class ListedValue:
    """One listed configuration value.

    ``applied`` is false only for a local override that the global file does
    not allow: it is shown, but the readers do not use it.
    """

    key: str
    value: str
    origin: ValueOrigin
    applied: bool = True


_URL_FIELDS = frozenset(
    {
        ("sync_root",),
        ("task_cache_s3",),
        ("publication", "clearml", "output_uri"),
        ("publication", "api_url"),
        ("publication", "s3_roots"),
    }
)


def _is_url_key(path: tuple[str, ...]) -> bool:
    """Say whether *path* names a URL-typed value, the only kind whose userinfo is hidden."""
    return path == ("cvat", "host") or (path[:1] == ("projects",) and path[2:] in _URL_FIELDS)


def _render(path: tuple[str, ...], value: object) -> str:
    """Render one value; the userinfo of a URL-typed value is never shown, whichever file or variable holds it.

    Other values are shown as they are: a username such as ``alice@example.com``
    stays readable.
    """
    hide = hide_url_userinfo if _is_url_key(path) else str
    if isinstance(value, list):
        return "[" + ", ".join(hide(str(item)) for item in cast("list[object]", value)) + "]"
    return hide(str(value))


def _dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _has(raw: dict[str, object], path: tuple[str, ...]) -> bool:
    node: object = raw
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            return False
        node = cast("dict[str, object]", node)[segment]
    return True


def _leaves(prefix: tuple[str, ...], value: object) -> list[tuple[tuple[str, ...], object]]:
    if isinstance(value, dict):
        mapping = cast("dict[str, object]", value)
        return [leaf for key, child in mapping.items() for leaf in _leaves((*prefix, key), child)]
    return [(prefix, value)]


def _env_int(name: str, minimum: int = 1) -> int | None:
    return _parse_int_env(name, minimum) if os.environ.get(name) else None


class _Lister:
    """Collects listed values in order; the first matching origin rule wins."""

    def __init__(self, personal: dict[str, object], shared: dict[str, object]) -> None:
        self.personal = personal
        self.shared = shared
        self.values: list[ListedValue] = []

    def add(
        self,
        path: tuple[str, ...],
        value: object,
        *,
        env: object = None,
        override: bool = False,
        hidden: bool = False,
    ) -> None:
        """Add one value; ``None`` (unset) is omitted. *env* is what the reader takes from the environment."""
        origin: ValueOrigin
        if env is not None:
            origin, value = "environment", env
        elif override:
            origin = "override"
        elif _has(self.shared, path):
            origin = "global"
        elif _has(self.personal, path):
            origin = "personal"
        else:
            origin = "default"
        if value is None:
            return
        self.values.append(ListedValue(".".join(path), _HIDDEN if hidden else _render(path, value), origin))

    def personal_value(self, path: tuple[str, ...], value: object) -> None:
        """Add a value that only the personal file holds, under a key the file may spell differently."""
        self.values.append(ListedValue(".".join(path), _render(path, value), "personal"))


def _cvat(lister: _Lister, personal: dict[str, object], shared: ProjectConfig | None) -> None:
    cvat = _dict(personal.get("cvat"))
    preset = _dict(_load_preset_data().get("cvat"))
    if shared is not None:
        host: object = shared.cvat.host
        organization: object = shared.cvat.organization
        env_host = env_organization = None
    else:
        host = cvat.get("host") or preset.get("host")
        organization = cvat.get("organization") or preset.get("organization")
        env_host, env_organization = os.environ.get("CVAT_HOST") or None, os.environ.get("CVAT_ORGANIZATION") or None
    timeout = cvat.get("request_timeout")
    lister.add(("cvat", "host"), host, env=env_host)
    lister.add(("cvat", "organization"), organization or None, env=env_organization)
    lister.add(("cvat", "username"), cvat.get("username") or None, env=os.environ.get("CVAT_USERNAME") or None)
    password = os.environ.get("CVAT_PASSWORD") or None
    lister.add(("cvat", "password"), cvat.get("password") or None, env=password, hidden=True)
    lister.add(
        ("cvat", "request_timeout"),
        timeout,
        env=_parse_timeout_env(os.environ.get("CVETA2_DATA_TIMEOUT")),
    )


def _sections(lister: _Lister, personal: dict[str, object], image_cache: dict[str, Path]) -> None:
    cache = CacheConfig.model_validate(_dict(personal.get("cache")))
    lister.add(("cache", "images_root"), cache.images_root)
    lister.add(("cache", "tasks_root"), cache.tasks_root)
    for name, path in image_cache.items():
        lister.personal_value(("image_cache", name), path)
    network = NetworkConfig.model_validate(_dict(personal.get("network")))
    lister.add(("network", "s3_workers"), network.s3_workers, env=_env_int("CVETA2_S3_WORKERS"))
    lister.add(("network", "cvat_workers"), network.cvat_workers, env=_env_int("CVETA2_CVAT_WORKERS"))
    lister.add(("network", "retry_attempts"), network.retry_attempts, env=_env_int("CVETA2_RETRY_ATTEMPTS", minimum=2))
    lister.add(("network", "retry_max_wait"), network.retry_max_wait)
    upload = UploadConfig.model_validate(_dict(personal.get("upload")))
    lister.add(("upload", "images_per_job"), upload.images_per_job)
    lister.add(("upload", "image_quality"), upload.image_quality)


def _projects(
    lister: _Lister,
    effective: ProjectConfig,
    overrides: LocalOverrides,
    *,
    applied: bool,
    keys: list[str],
) -> None:
    overridden = {leaf.removeprefix("overrides.") for leaf in override_leaves(overrides)} if applied else set()
    refused = _dict(overrides.model_dump(exclude_none=True).get("projects")) if not applied else {}
    for key in keys:
        project = effective.projects[key]
        for field in _PROJECT_FIELDS:
            lister.add(("projects", key, field), getattr(project, field))
        if project.publication is not None:
            for path, value in _leaves(("projects", key, "publication"), project.publication.model_dump(mode="json")):
                lister.add(path, value, override=".".join(path) in overridden)
        for path, value in _leaves(("projects", key), refused.get(key, {})):
            lister.values.append(ListedValue(".".join(path), _render(path, value), "override", applied=False))


def list_configuration(
    personal_path: Path, *, global_path: Path | None = None, project: str | None = None, live_name: str | None = None
) -> list[ListedValue]:
    """List the effective configuration with the origin of each value.

    *global_path* selects the global file like ``--global-config``; nothing
    is attached. With *project* (a key, name or ID) only that project's
    entries and its ``image_cache`` path are listed. ``ignore`` and
    ``datasets`` are not listed.
    """
    selected = project_config_path(personal_path, global_path)
    personal = read_config(personal_path, missing_ok=True)
    shared = optional_global_config(personal_path, global_path) if selected is not None else None
    raw_shared = read_config(selected) if selected is not None else {}
    overrides = read_local_overrides(personal)
    applied = shared is None or shared.local_overrides or not override_leaves(overrides)
    effective = apply_local_overrides(shared, overrides) if shared is not None and applied else shared
    image_cache = ImageCacheConfig.model_validate({"projects": personal.get("image_cache") or {}}).projects
    lister = _Lister(personal, raw_shared)
    if project is None:
        _cvat(lister, personal, shared)
        _sections(lister, personal, image_cache)
        if shared is not None and effective is not None:
            lister.add(("local_overrides",), shared.local_overrides)
            _projects(lister, effective, overrides, applied=applied, keys=list(effective.projects))
        return lister.values
    key = find_project_key(shared, project) if shared is not None else None
    name = key or project
    if name not in image_cache and live_name is not None:
        name = live_name
    if key is None and name not in image_cache:
        raise Cveta2Error(f"Проект {project} не найден ни в общей конфигурации, ни в разделе image_cache.")
    if name in image_cache:
        lister.personal_value(("image_cache", name), image_cache[name])
    if effective is not None and key is not None:
        _projects(lister, effective, overrides, applied=applied, keys=[key])
    return lister.values

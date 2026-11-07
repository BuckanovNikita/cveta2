"""Authoritative shared project configuration and reviewed legacy migration.

Personal credentials and local paths are never merged into project policy. The
migration journal records only paths and hashes; secret-bearing stages/backups
are private files, and the shared target is always claimed exclusively.
"""

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

import yaml
from pydantic import JsonValue, ValidationError

from cveta2.domain.managed.models import (
    ManagedError,
    MigrationRequired,
    ProjectConfig,
    ProjectDefinition,
)

_PERSONAL_KEYS = {
    "schema_version",
    "project_config",
    "cvat",
    "image_cache",
    "cache",
    "network",
    "upload",
}
_SHARED_KEYS = {"projects", "datasets", "sync_roots", "ignore", "clearml"}
_POLICY_KEYS = {"ignored_prefix", "task_cache_s3"}


def _check_nodes(node: yaml.Node, active: set[int]) -> None:
    """Reject duplicate/non-string mapping keys and recursive aliases."""
    if id(node) in active:
        raise ManagedError("Recursive YAML configuration is unsupported")
    active.add(id(node))
    if isinstance(node, yaml.MappingNode):
        keys: set[str] = set()
        for key, value in node.value:
            if not isinstance(key, yaml.ScalarNode) or key.tag != "tag:yaml.org,2002:str" or key.value in keys:
                raise ManagedError("Configuration mapping keys must be unique strings")
            keys.add(key.value)
            _check_nodes(value, active)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _check_nodes(item, active)
    active.remove(id(node))


def personal_config_path(path: Path | None = None) -> Path:
    """Resolve personal configuration independently of project selection."""
    return (
        path
        if path is not None
        else Path(os.environ.get("CVETA2_CONFIG", str(Path.home() / ".config/cveta2/config.yaml")))
    )


def read_config(path: Path, *, missing_ok: bool = False) -> dict[str, object]:
    """Read a strict YAML mapping without exposing source scalars on failures."""
    if missing_ok and not path.exists():
        return {}
    try:
        content = path.read_bytes()
        node = yaml.compose(content, Loader=yaml.SafeLoader)
        if node is not None:
            _check_nodes(node, set())
        raw: object = yaml.safe_load(content)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ManagedError(f"Cannot read configuration {path}: {type(error).__name__}") from error
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ManagedError(f"Configuration must be a mapping: {path}")
    return cast("dict[str, object]", raw)


def _dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _mixed_policy(raw: dict[str, object]) -> bool:
    if any(raw.get(key) for key in _SHARED_KEYS):
        return True
    return any(
        any(_dict(value).get(key) is not None for key in _POLICY_KEYS)
        for value in _dict(_dict(raw.get("cache")).get("projects")).values()
    )


def validate_personal(raw: dict[str, object], *, attached: bool = False) -> None:
    """Reject shared-owned fields instead of treating them as overrides."""
    if raw.get("schema_version") not in (None, 1):
        raise ManagedError("Unsupported personal configuration schema_version")
    cvat = _dict(raw.get("cvat"))
    if raw.get("schema_version") == 1:
        if set(raw) - _PERSONAL_KEYS:
            raise ManagedError("Personal configuration contains unsupported/shared sections")
        cache_projects = _dict(_dict(raw.get("cache")).get("projects"))
        misplaced_cache = any(set(_dict(value)) & _POLICY_KEYS for value in cache_projects.values())
        if _mixed_policy(raw) or misplaced_cache or "host" in cvat or "organization" in cvat:
            raise ManagedError("Shared project policy/identity cannot be stored in personal configuration")
        if set(cvat) - {"username", "password", "request_timeout"}:
            raise ManagedError("Unknown personal CVAT setting")
    elif _mixed_policy(raw) or (attached and ("host" in cvat or "organization" in cvat)):
        raise MigrationRequired("Legacy mixed configuration requires verification: cveta2 setup --migrate-config")


def project_config_path(personal_path: Path | None = None, project_path: Path | None = None) -> Path | None:
    """Select one shared file; never overlay definitions from multiple files."""
    personal = personal_config_path(personal_path)
    raw = read_config(personal, missing_ok=True)
    explicit = project_path or (
        Path(os.environ["CVETA2_PROJECT_CONFIG"]) if os.environ.get("CVETA2_PROJECT_CONFIG") else None
    )
    saved = raw.get("project_config")
    if saved is not None and (not isinstance(saved, str) or not saved.strip()):
        raise ManagedError("project_config must be a nonempty file path")
    selected = explicit
    if selected is None and isinstance(saved, str):
        selected = Path(saved)
        if not selected.is_absolute():
            selected = personal.parent / selected
    validate_personal(raw, attached=selected is not None)
    if raw.get("schema_version") == 1 and selected is None:
        raise ManagedError("Versioned personal configuration requires a shared project_config reference")
    return selected.expanduser().resolve() if selected is not None else None


def load_project_config(personal_path: Path | None = None, project_path: Path | None = None) -> ProjectConfig:
    """Load the one selected authoritative shared project definition."""
    path = project_config_path(personal_path, project_path)
    if path is None:
        raise ManagedError(
            "Shared project configuration is not attached; use setup --project-config PATH or CVETA2_PROJECT_CONFIG"
        )
    try:
        return ProjectConfig.model_validate(read_config(path))
    except ValidationError as error:
        fields = ", ".join(".".join(str(part) for part in issue["loc"]) for issue in error.errors())
        raise ManagedError(f"Invalid shared project configuration {path}; fields: {fields}") from error


def optional_project_config(
    personal_path: Path | None = None, project_path: Path | None = None
) -> ProjectConfig | None:
    """Return no definition only when no shared file was selected."""
    return (
        load_project_config(personal_path, project_path)
        if project_config_path(personal_path, project_path) is not None
        else None
    )


def _yaml_bytes(data: dict[str, object]) -> bytes:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode("utf-8")


def _stage_bytes(path: Path, content: bytes, purpose: str) -> Path:
    """Create an exclusively claimed private stage beside its destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.{purpose}-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
    return temporary


def _private_write(
    path: Path,
    content: bytes,
    *,
    replace: bool = False,
    preserve_permissions: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
        except OSError:
            path.unlink(missing_ok=True)
            raise
        return
    metadata = path.stat() if preserve_permissions else None
    temporary = _stage_bytes(path, content, "replace")
    try:
        if metadata is not None:
            # Atomic replacement must retain the shared group as well as its
            # access bits; the temporary otherwise inherits the writer's group.
            if os.name != "nt":
                os.chown(temporary, -1, metadata.st_gid)
            temporary.chmod(stat.S_IMODE(metadata.st_mode))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def attach_project_config(personal_path: Path, project_path: Path) -> Path:
    """Validate and save an absolute reference without changing shared bytes."""
    selected = project_path.expanduser().resolve()
    raw = read_config(personal_path, missing_ok=True)
    validate_personal(raw, attached=True)
    try:
        ProjectConfig.model_validate(read_config(selected))
    except ValidationError as error:
        raise ManagedError(f"Invalid shared project configuration: {selected}") from error
    raw["schema_version"] = 1
    raw["project_config"] = str(selected)
    try:
        validate_personal(raw, attached=True)
    except ManagedError as error:
        raise MigrationRequired(
            "Legacy fields require reviewed separation before attachment: cveta2 setup --migrate-config"
        ) from error
    _private_write(personal_path, _yaml_bytes(raw), replace=True)
    return selected


def shared_projects_by_name(config: ProjectConfig) -> dict[str, ProjectDefinition]:
    """Resolve old name-based reader APIs without silently accepting ambiguity."""
    result: dict[str, ProjectDefinition] = {}
    for key, project in config.projects.items():
        for name in {key, project.name} - {""}:
            if name in result and result[name].id != project.id:
                raise ManagedError(f"Ambiguous shared project name: {name}")
            result[name] = project
    return result


def write_shared_project_fields(personal_path: Path, changes: dict[str, dict[str, object]]) -> Path:
    """Explicit policy writers update shared fields; no personal shadow copies."""
    path = project_config_path(personal_path)
    if path is None:
        raise ManagedError("No shared project configuration is selected")
    config = load_project_config(personal_path)
    projects = dict(config.projects)
    aliases = shared_projects_by_name(config)
    for name, fields in changes.items():
        project = aliases.get(name)
        if project is None:
            raise ManagedError(f"Unknown shared project: {name}")
        key = next(key for key, value in projects.items() if value.id == project.id)
        projects[key] = ProjectDefinition.model_validate({**project.model_dump(), **fields})
    updated = ProjectConfig.model_validate(
        {
            **config.model_dump(),
            "projects": {k: p.model_dump() for k, p in projects.items()},
        }
    )
    # Mode-bit check gives a useful refusal even when an elevated process could
    # replace a read-only file through its writable parent directory.
    if path.stat().st_mode & 0o222 == 0:
        raise ManagedError(f"Shared project configuration is read-only: {path}")
    _private_write(path, _yaml_bytes(updated.model_dump()), replace=True, preserve_permissions=True)
    return path


@dataclass(frozen=True)
class MigrationProposal:
    """Concrete reviewed documents and source fingerprint, before any writes."""

    personal_path: Path
    shared_path: Path
    original_hash: str
    personal: dict[str, object]
    shared: dict[str, object]
    unresolved: tuple[str, ...]

    def preview(self) -> dict[str, object]:
        """Expose destination/ownership without ever printing credentials."""
        personal = dict(self.personal)
        cvat = _dict(personal.get("cvat"))
        personal["cvat"] = {
            key: "<redacted>" if key in {"username", "password"} else value for key, value in cvat.items()
        }
        return {
            "personal_path": str(self.personal_path),
            "shared_path": str(self.shared_path),
            "personal": personal,
            "shared": self.shared,
            "unresolved": list(self.unresolved),
        }


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _cached_projects(personal_path: Path, organization: object) -> dict[str, list[int]]:
    raw = read_config(personal_path.parent / "projects.yaml", missing_ok=True)
    result: dict[str, list[int]] = {}
    organizations = raw.get("organizations")
    if not isinstance(organizations, list):
        return result
    for item in organizations:
        entry = _dict(item)
        if entry.get("slug", "") != (organization or ""):
            continue
        projects = entry.get("projects")
        if isinstance(projects, list):
            for value in projects:
                project = _dict(value)
                if isinstance(project.get("name"), str) and isinstance(project.get("id"), int):
                    result.setdefault(str(project["name"]), []).append(cast("int", project["id"]))
    return result


def _migration_projects(
    raw: dict[str, object], cached: dict[str, list[int]], unresolved: list[str]
) -> dict[str, object]:
    """Move only projects whose identity is supported by the discovery cache."""
    cache = _dict(raw.get("cache"))
    sync = _dict(raw.get("sync_roots"))
    ignores = _dict(raw.get("ignore"))
    cache_projects = _dict(cache.get("projects"))
    names = set(sync) | set(ignores) | set(cache_projects) | set(cached)
    projects: dict[str, object] = {}
    for name in sorted(names):
        ids = set(cached.get(name, []))
        if len(ids) != 1:
            unresolved.append(f"Project {name!r} requires an unambiguous cached CVAT identity")
            continue
        project_id = ids.pop()
        key = name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name) else f"project-{project_id}"
        if key in projects:
            unresolved.append(
                f"Project key collision for {name!r}: {key!r}; review the legacy identities before migration"
            )
            continue
        policies = _dict(cache_projects.get(name))
        entries = ignores.get(name, [])
        ignore_rows: list[dict[str, JsonValue]] = []
        if isinstance(entries, list):
            for value in entries:
                if isinstance(value, int) and not isinstance(value, bool):
                    ignore_rows.append({"id": value, "name": ""})
                elif isinstance(value, str) and value.strip().isdigit():
                    ignore_rows.append({"id": int(value), "name": ""})
                elif isinstance(value, dict):
                    try:
                        ignore_rows.append(
                            {
                                "id": int(value["id"]),
                                "name": str(value.get("name", "")),
                                "description": str(value.get("description", "")),
                                "silent": bool(value.get("silent")),
                            }
                        )
                    except (KeyError, TypeError, ValueError):
                        unresolved.append(f"Invalid ignored-task record for {name!r}")
                else:
                    unresolved.append(f"Unclassified ignored-task record for {name!r}")
        projects[key] = {
            "id": project_id,
            "name": name,
            "sync_root": sync.get(name),
            "ignore": ignore_rows,
            **{field: policies.get(field) for field in _POLICY_KEYS},
        }
    return projects


def _unknown_legacy_fields(raw: dict[str, object]) -> list[str]:
    """Report unsupported nested fields instead of discarding their values."""
    paths = [
        f"cvat.{key}"
        for key in set(_dict(raw.get("cvat"))) - {"host", "organization", "username", "password", "request_timeout"}
    ]
    cache = _dict(raw.get("cache"))
    paths.extend(f"cache.{key}" for key in set(cache) - {"images_root", "tasks_root", "projects"})
    for name, fields in _dict(cache.get("projects")).items():
        paths.extend(
            f"cache.projects.{name}.{key}"
            for key in set(_dict(fields)) - {"images_root", "tasks_root", "ignored_prefix", "task_cache_s3"}
        )
    return sorted(paths)


def migration_proposal(personal_path: Path, project_path: Path | None = None) -> MigrationProposal:
    """Split known legacy fields without inventing project identities."""
    personal_path = personal_path.expanduser().resolve()
    original = personal_path.read_bytes()
    raw = read_config(personal_path)
    if raw.get("schema_version") == 1:
        selected = project_config_path(personal_path, project_path)
        if selected is None:
            raise ManagedError("Versioned personal configuration has no shared reference")
        return MigrationProposal(
            personal_path,
            selected,
            _digest(original),
            raw,
            load_project_config(personal_path, selected).model_dump(),
            (),
        )
    cvat = _dict(raw.get("cvat"))
    unresolved = [f"Unclassified legacy field remains in backup: {field}" for field in _unknown_legacy_fields(raw)]
    host = cvat.get("host") or os.environ.get("CVAT_HOST")
    if not isinstance(host, str) or not host:
        unresolved.append("CVAT host is missing")
        host = "http://unresolved.invalid"
    organization = cvat.get("organization")
    projects = _migration_projects(raw, _cached_projects(personal_path, organization), unresolved)
    cache = _dict(raw.get("cache"))
    cache_projects = _dict(cache.get("projects"))
    known = {
        "cvat",
        "cache",
        "image_cache",
        "sync_roots",
        "ignore",
        "network",
        "upload",
        "project_config",
    }
    unknown = set(raw) - known
    if unknown:
        unresolved.append("Unclassified legacy sections remain only in backup: " + ", ".join(sorted(unknown)))
    personal = {key: value for key, value in raw.items() if key in {"image_cache", "network", "upload"}}
    personal["cvat"] = {key: value for key, value in cvat.items() if key in {"username", "password", "request_timeout"}}
    local_cache = {key: value for key, value in cache.items() if key in {"images_root", "tasks_root"}}
    local_projects = {
        name: {key: value for key, value in _dict(fields).items() if key in {"images_root", "tasks_root"}}
        for name, fields in cache_projects.items()
    }
    local_cache["projects"] = {name: fields for name, fields in local_projects.items() if fields}
    if local_cache:
        personal["cache"] = local_cache
    shared_path = (project_path or personal_path.with_name("project-config.yaml")).expanduser().resolve()
    personal.update(schema_version=1, project_config=str(shared_path))
    shared: dict[str, object] = {
        "schema_version": 1,
        "cvat": {"host": host, "organization": organization},
        "projects": projects,
        "datasets": {},
    }
    if not unresolved:
        shared = ProjectConfig.model_validate(shared).model_dump()
    if shared_path.exists() and read_config(shared_path) != shared:
        unresolved.append("Existing shared configuration differs; reconcile it explicitly before migration")
    return MigrationProposal(
        personal_path,
        shared_path,
        _digest(original),
        personal,
        shared,
        tuple(unresolved),
    )


def _journal_path(personal_path: Path) -> Path:
    return personal_path.with_name(f"{personal_path.name}.migration.json")


def recover_migration(personal_path: Path) -> bool:
    """Complete a previously approved activation using verified staged bytes."""
    journal_path = _journal_path(personal_path)
    if not journal_path.exists():
        return False
    journal = cast("dict[str, str]", json.loads(journal_path.read_bytes()))
    shared = Path(journal["shared_path"])
    staged_shared = Path(journal["staged_shared"])
    staged_personal = Path(journal["staged_personal"])
    if shared.exists():
        if _digest(shared.read_bytes()) != journal["shared_hash"]:
            raise ManagedError("Migration recovery found a conflicting shared file")
    else:
        if _digest(staged_shared.read_bytes()) != journal["shared_hash"]:
            raise ManagedError("Migration shared stage changed")
        os.link(staged_shared, shared)
    current_hash = _digest(personal_path.read_bytes())
    if current_hash != journal["personal_hash"]:
        if current_hash != journal["original_hash"]:
            raise ManagedError("Personal configuration changed during migration recovery")
        if _digest(staged_personal.read_bytes()) != journal["personal_hash"]:
            raise ManagedError("Migration personal stage changed")
        staged_personal.replace(personal_path)
    staged_personal.unlink(missing_ok=True)
    staged_shared.unlink(missing_ok=True)
    journal_path.unlink()
    return True


def _claim_migration_journal(proposal: MigrationProposal, personal_bytes: bytes, shared_bytes: bytes) -> None:
    """Claim one approved transaction without replacing another writer's journal."""
    staged_personal = _stage_bytes(proposal.personal_path, personal_bytes, "migration")
    try:
        staged_shared = _stage_bytes(proposal.shared_path, shared_bytes, "migration")
    except OSError:
        staged_personal.unlink(missing_ok=True)
        raise
    journal = {
        "shared_path": str(proposal.shared_path),
        "staged_shared": str(staged_shared),
        "staged_personal": str(staged_personal),
        "shared_hash": _digest(shared_bytes),
        "personal_hash": _digest(personal_bytes),
        "original_hash": proposal.original_hash,
    }
    try:
        _private_write(_journal_path(proposal.personal_path), json.dumps(journal).encode())
    except FileExistsError as error:
        staged_personal.unlink(missing_ok=True)
        staged_shared.unlink(missing_ok=True)
        raise ManagedError("Another approved migration is active; run setup --migrate-config again") from error
    except OSError:
        staged_personal.unlink(missing_ok=True)
        staged_shared.unlink(missing_ok=True)
        raise


def activate_migration(proposal: MigrationProposal) -> Path:
    """Activate only the exact approved proposal, retaining a private backup."""
    if proposal.unresolved:
        raise ManagedError("Migration has unresolved settings: " + "; ".join(proposal.unresolved))
    if recover_migration(proposal.personal_path):
        return proposal.shared_path
    original = proposal.personal_path.read_bytes()
    if _digest(original) != proposal.original_hash:
        raise ManagedError("Configuration changed after migration preview; review again")
    validate_personal(proposal.personal, attached=True)
    ProjectConfig.model_validate(proposal.shared)
    shared_bytes, personal_bytes = (
        _yaml_bytes(proposal.shared),
        _yaml_bytes(proposal.personal),
    )
    if proposal.shared_path.exists() and proposal.shared_path.read_bytes() != shared_bytes:
        # Compare semantics as a pre-existing human file may use other formatting.
        if read_config(proposal.shared_path) != proposal.shared:
            raise ManagedError("Existing shared file differs; it will not be overwritten")
        shared_bytes = proposal.shared_path.read_bytes()
    if proposal.personal == read_config(proposal.personal_path):
        return proposal.shared_path
    backup = proposal.personal_path.with_name(f"{proposal.personal_path.name}.pre-v1-{proposal.original_hash[:12]}.bak")
    if backup.exists():
        if backup.read_bytes() != original:
            raise ManagedError("Migration backup conflicts")
    else:
        _private_write(backup, original)
    _claim_migration_journal(proposal, personal_bytes, shared_bytes)
    recover_migration(proposal.personal_path)
    return proposal.shared_path

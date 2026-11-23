"""Local overrides: per-user publication settings layered over the global file.

The effective configuration is the global file with the allowed overrides
merged in, per leaf; a list replaces the global list as a whole. Only
publication settings are overridable, so every teammate fetches the same data.
"""

from typing import cast

from pydantic import Field, ValidationError

from cveta2.domain.managed.models import ManagedError, ProjectConfig, StrictModel

OVERRIDABLE_PROJECT_FIELDS: frozenset[str] = frozenset({"publication"})


class ClearMLOverride(StrictModel):
    """Any subset of a ClearML destination."""

    project: str | None = None
    dataset: str | None = None
    output_uri: str | None = None


class PublicationOverride(StrictModel):
    """Any subset of a project's publication settings."""

    clearml: ClearMLOverride | None = None
    api_url: str | None = None
    empty_classes: list[int] | None = None
    s3_roots: list[str] | None = None


class ProjectOverride(StrictModel):
    """The overridable part of one project definition; every other key is rejected."""

    publication: PublicationOverride | None = None


class LocalOverrides(StrictModel):
    """The ``overrides`` section of a personal file, keyed like ``projects`` in the global file."""

    projects: dict[str, ProjectOverride] = Field(default_factory=dict)


class LocalOverridesDisabledError(ManagedError):
    """The personal file carries overrides that the global file does not allow."""


def _leaves(prefix: str, value: object) -> list[str]:
    if isinstance(value, dict):
        mapping = cast("dict[str, object]", value)
        return [leaf for key, child in mapping.items() for leaf in _leaves(f"{prefix}.{key}", child)]
    return [prefix]


def override_leaves(overrides: LocalOverrides) -> list[str]:
    """Sorted dotted paths of the set leaves, for example ``overrides.projects.retail.publication.clearml.dataset``."""
    return sorted(_leaves("overrides", overrides.model_dump(exclude_none=True)))


def _deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    """Merge mappings recursively; let lists and scalars replace."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = _deep_merge(cast("dict[str, object]", current), cast("dict[str, object]", value))
        else:
            merged[key] = value
    return merged


def apply_local_overrides(config: ProjectConfig, overrides: LocalOverrides) -> ProjectConfig:
    """Return the effective configuration: *config* with the allowed overrides merged in."""
    if not overrides.projects:
        return config
    if not config.local_overrides:
        raise LocalOverridesDisabledError(
            f"Личная конфигурация содержит локальные переопределения ({', '.join(override_leaves(overrides))}), "
            "но общая конфигурация их не разрешает. Удалите их из раздела overrides личного файла "
            "или попросите команду выполнить: cveta2 setup --global --local-overrides on"
        )
    unknown = sorted(set(overrides.projects) - set(config.projects))
    if unknown:
        raise ManagedError(
            "Локальные переопределения ссылаются на проекты, которых нет в общей конфигурации: " + ", ".join(unknown)
        )
    merged = config.model_dump(mode="json")
    projects = cast("dict[str, dict[str, object]]", merged["projects"])
    for key, override in overrides.projects.items():
        projects[key] = _deep_merge(projects[key], override.model_dump(exclude_none=True))
    try:
        return ProjectConfig.model_validate(merged)
    except ValidationError as error:
        issues = error.errors()
        fields = ", ".join(".".join(str(part) for part in issue["loc"]) for issue in issues)
        raise ManagedError(
            f"Локальные переопределения делают общую конфигурацию некорректной; поля: {fields}; {issues[0]['msg']}"
        ) from error

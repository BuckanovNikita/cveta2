"""Configuration and selection services exposed at entry boundaries."""

from pathlib import Path

from cveta2.adapters.config.project import (
    GLOBAL_CONFIG_ENV,
    LEGACY_GLOBAL_CONFIG_ENV,
    MigrationProposal,
    SharedIdentityMismatchError,
    activate_migration,
    attach_existing_project_config,
    attach_project_config,
    create_global_config,
    find_project_key,
    global_config_from_env,
    load_global_config,
    load_project_config,
    migration_proposal,
    optional_global_config,
    optional_project_config,
    project_config_path,
    project_key_for,
    read_local_overrides,
    recover_migration,
    select_spelling,
    write_local_overrides,
    write_shared_project_fields,
)
from cveta2.adapters.config.projects_cache import (
    PERSONAL_WORKSPACE_SLUG,
    PERSONAL_WORKSPACE_TITLE,
    OrgProjects,
    load_orgs_cache,
    load_projects_cache,
    save_orgs_cache,
    update_org_projects,
)
from cveta2.adapters.config.settings import (
    CONFIG_DIR,
    CONFIG_PATH,
    CacheConfig,
    CvatConfig,
    IgnoreConfig,
    ImageCacheConfig,
    NetworkConfig,
    SectionConfig,
    SyncRootsConfig,
    UploadConfig,
    cache_dir_for_project,
    get_config_path,
    get_projects_cache_path,
    images_cache_dir_from,
    is_cache_disabled,
    is_interactive_disabled,
    require_interactive,
    resolve_images_cache_dir,
    should_raise_on_fetch_failure,
)
from cveta2.application.settings import (
    CacheProjectSettings,
    IgnoredTask,
)
from cveta2.domain.managed.models import PublicationSettings
from cveta2.domain.managed.overrides import (
    OVERRIDABLE_PROJECT_FIELDS,
    ClearMLOverride,
    LocalOverrides,
    LocalOverridesDisabledError,
    ProjectOverride,
    PublicationOverride,
    apply_local_overrides,
    override_leaves,
)

__all__ = [
    "CONFIG_DIR",
    "CONFIG_PATH",
    "GLOBAL_CONFIG_ENV",
    "LEGACY_GLOBAL_CONFIG_ENV",
    "OVERRIDABLE_PROJECT_FIELDS",
    "PERSONAL_WORKSPACE_SLUG",
    "PERSONAL_WORKSPACE_TITLE",
    "CacheConfig",
    "CacheProjectSettings",
    "ClearMLOverride",
    "CvatConfig",
    "IgnoreConfig",
    "IgnoredTask",
    "ImageCacheConfig",
    "LocalOverrides",
    "LocalOverridesDisabledError",
    "MigrationProposal",
    "NetworkConfig",
    "OrgProjects",
    "ProjectOverride",
    "PublicationOverride",
    "SectionConfig",
    "SharedIdentityMismatchError",
    "SyncRootsConfig",
    "UploadConfig",
    "activate_migration",
    "apply_local_overrides",
    "attach_existing_project_config",
    "attach_project_config",
    "cache_dir_for_project",
    "create_global_config",
    "find_project_key",
    "get_config_path",
    "get_projects_cache_path",
    "global_config_from_env",
    "images_cache_dir_from",
    "is_cache_disabled",
    "is_interactive_disabled",
    "load_global_config",
    "load_orgs_cache",
    "load_project_config",
    "load_projects_cache",
    "migration_proposal",
    "optional_global_config",
    "optional_project_config",
    "override_leaves",
    "project_config_path",
    "project_key_for",
    "project_publication",
    "read_local_overrides",
    "recover_migration",
    "require_interactive",
    "resolve_images_cache_dir",
    "save_orgs_cache",
    "select_spelling",
    "should_raise_on_fetch_failure",
    "update_org_projects",
    "write_local_overrides",
    "write_shared_project_fields",
]


def project_publication(
    project_id: int, *, config_path: Path | None = None, project_config: Path | None = None
) -> PublicationSettings | None:
    """Return the effective publication settings of the CVAT project *project_id*, if any.

    No global file, an unknown project or a project without ``publication``
    all return ``None``; the caller then needs the values from elsewhere.
    """
    config = optional_project_config(get_config_path(config_path), project_config)
    if config is None:
        return None
    return next((p.publication for p in config.projects.values() if p.id == project_id), None)

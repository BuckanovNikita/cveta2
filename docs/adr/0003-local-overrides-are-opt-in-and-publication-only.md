# Limit personal overrides to publication settings

The global configuration owns the team’s CVAT server, project identities, storage policy, ignore lists and managed dataset definitions. A personal configuration may override a project’s publication settings only when the global file opts in with `local_overrides: true`. Omitting that switch preserves the default for existing and migrated configurations.

| Personal publication override | Values |
| --- | --- |
| ClearML destination | Project, dataset name, output URI |
| Training inputs | Class API URL, excluded classes, S3 image roots |

A user can publish a trial dataset to a personal destination. The shared identity and source rules keep two users working with the same team data. A write to the global configuration starts from the raw global file so a personal override cannot leak into it. [config overrides tests](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_config_overrides.py)

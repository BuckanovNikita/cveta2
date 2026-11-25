# Local overrides are opt-in and cover publication settings only

The global configuration is the team's single source for its CVAT server, projects, publication settings and managed datasets. A user may override a project's values in the personal configuration (`overrides.projects.<key>`) only when the global file sets `local_overrides: true`. Without that switch, the key is absent and overrides are rejected, so existing and migrated configurations keep their strictness.

Even when allowed, an override can replace only publication settings:

- the ClearML project;
- the dataset name;
- `output_uri`;
- the class API URL;
- excluded classes;
- S3 roots.

It cannot replace a project's identity, sync root, ignored prefix, task cache or ignore list. It cannot replace `datasets.<name>` entries, which define managed datasets and their lineage. Writes to the global configuration always start from the raw global file, never from a user's effective view, so one user's override never leaks into the team file.

Why: publication targets legitimately differ per user, for example a personal ClearML project for a trial upload. Everything else either identifies shared data or decides what a published version contains. If those differed per user, two people could publish different datasets under one name.

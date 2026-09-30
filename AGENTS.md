# cveta2 agent entry point

cveta2 is a Python 3.10+ CVAT CLI and API. Run Python tools through `uv run`.
User messages and human guides are Russian; Spec Kit artifacts are English.
This file is the shared discovery entry point; `CLAUDE.md` is its symlink.
Edit canonical sources below rather than duplicating their rules here.

Before planning or editing, read:

1. [Spec Kit constitution](.specify/memory/constitution.md) for project principles.
2. [Engineering guidance](.specify/memory/engineering.md) for the required
   workflow, verification, working-tree ownership, integration, and release rules.
3. [Architecture context](.specify/memory/architecture.md) when changing module
   flow, project resolution, fetch/upload, or conversion behavior.
4. [Dataset contract](specs/001-project-documentation/contracts/dataset-format.md)
   when changing exported data or conversion behavior.

Use `$speckit-<step>` in Codex and `/speckit-<step>` in Claude. Follow the full
sequence in engineering guidance; select the active feature explicitly before
writing artifacts. Executable commit, mutation, and integration skills remain
applicable within that workflow. Human setup and invocation examples are in
[CONTRIBUTING.md](CONTRIBUTING.md).

# Build installable artifacts locally and derive releases from merged changes

## Package build

The package supplies the version and CLI entry point. The wheel ships the package, and the source distribution uses an explicit inclusion list. The build task removes its temporary output after validation. Users can install from a Git tag or revision. [Build and version configuration](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/pyproject.toml) · [Build task](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml)

## Release trigger

Closing a merged PR into main triggers a serialized job on main with full history. Semantic-release uses Conventional Commits to determine the package version, changelog and Git tag. The workflow runs with `--no-vcs-release` and ends without publishing a wheel to a registry. [Release workflow](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/.github/workflows/release.yml) · [Versioning rules](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/pyproject.toml)

## Main protection

A repository ruleset on `main` blocks deletion and force pushes and requires changes to arrive through a pull request, with no required approvals or status checks. The release job pushes the release commit and tag straight to `main`. `GITHUB_TOKEN` cannot be a ruleset bypass actor on a user-owned repository, so the job checks out with a write deploy key (secret `RELEASE_DEPLOY_KEY`) that the ruleset lists as a bypass actor. Do not add required signatures, required linear history or a required status check without changing the release job: the release commit is unsigned and is pushed without a pull request.

## GitHub triggers

PR open, synchronize, ready-for-review and reopen events trigger automated review. Eligible issue and review events mentioning `@claude` invoke a separate workflow. The original rationale for these triggers is unknown. [PR review](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/.github/workflows/claude-code-review.yml) · [Mention workflow](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/.github/workflows/claude.yml)

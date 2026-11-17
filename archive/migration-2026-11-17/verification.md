# Archive and release suspension evidence — 2026-11-17

Source cveta2 commit: `63cd255`; working branch: `chore/linear-workflow`.

- `uv sync --locked` passed with the worktree-owned Python 3.12 environment.
  No lockfile change was needed.
- All 18 archived skill files matched their SHA-256 manifest; neither host's active
  skill directory retained a `speckit-*` entry. This checks byte preservation, not
  whether an already-running host has refreshed its cached skill catalogue.
- `uv run --locked semantic-release --noop version --no-push --no-vcs-release`
  reported that `chore/linear-workflow` belongs to no release group. The command
  exits 0 for this refusal; tracked file hashes and tags were unchanged.
- An isolated temporary local clone checked out on `main`, using the modified
  release configuration and the worktree's semantic-release executable, reported
  `branch 'main' isn't in any release groups; no release will be made` under the
  same no-operation flags. Tracked file hashes and tags were unchanged. The clone
  was removed after the check. The shared main checkout was not modified.
- `uv run --locked task --exit-code build` passed and built both sdist and wheel.
  Task removed its temporary output directory.

These are focused checks, not full development or live acceptance. The guard
suspends the configured semantic-release route; it does not prevent deliberately
using alternate configuration or manually creating tags. No release was attempted
without no-operation mode, and no tags or remote refs were written by these checks.

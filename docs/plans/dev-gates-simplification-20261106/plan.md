# Development gates simplification: maintenance plan

Date: 2026-11-06. Decision: the owner chose option A (mutation testing becomes
advisory and scoped to the change). Every long-running check moves into the
pre-commit stage so that no pre-push stage needs customizing. Mutation runs no
longer share a cache. The commit and integration skills shrink to what the tools do
not already enforce.

## Workflow selection

This is development-tooling and governance maintenance. The `cveta2` package, its
CLI, its public API and the dataset contract do not change. Per
[engineering guidance](../../../.specify/memory/engineering.md#spec-kit-development-workflow)
it therefore takes the lightweight path: this plan, [tasks.md](tasks.md), an adjacent
[architecture.json](architecture.json) and dated verification evidence. That matches
the [scripts simplification](../scripts-simplification-20261106/plan.md) precedent.
The constitution amendment uses the Spec Kit constitution format, with a version
bump and a sync impact report. `.specify/feature.json` (spec 005) is not touched.

## Accepted behaviour losses

- **Mutation no longer blocks.** The zero-survivor ratchet, the 68-module
  `only_mutate` list, the fast/full profiles and the 305-entry equivalent-mutant
  allowlist are removed. A commit that changes `cveta2/**/*.py` mutates only the
  changed functions and prints the survivors, then passes. Only a tool or
  configuration failure fails the hook.
- **The diff base is the staged change against `HEAD`**, not the branch against
  `main`. Functions changed in earlier commits are not re-tested.
- **A commit that only deletes files** runs no file-filtered hook. pre-commit
  lists only added or modified staged files, so neither the mutation run nor the
  live gate starts.
- **Concurrent live suites are not capped by tooling.** Every armed worktree
  that commits gated paths starts one. The registry cap is documented in the
  integration skill, but `room` does not enforce it.
- **Version drift is no longer checked.** That check cannot work at commit time: the
  release's bump commit exists before its tag. semantic-release remains the only
  writer of `project.version`.
- **Rebase, cherry-pick and merge commits run no pre-commit hooks**, so they are
  pushed without a safety net. The remedy is documented: run
  `uv run pre-commit run --all-files`, plus `scripts/mutation.py --base
  <upstream>` for the mutation report, after rewriting history.
- **The integration gate can block commits.** It runs on commits that touch
  `cveta2/`, `tests/integration/`, `pyproject.toml` or `uv.lock`. The following now
  fail the commit, where before they failed the push:
  - a stand that is down;
  - a `room` WAIT;
  - an active `tests/integration/.run-tag` in the checkout.

  Pre-commit also keeps unstaged changes stashed for the minutes the gate runs, so
  nobody should edit the checkout during a commit.
- **semantic-release's release commit runs hooks.** Its files are `pyproject.toml`,
  `uv.lock` and `CHANGELOG.md`, so it runs the integration gate once, in the
  durable `cveta2-main` slot. That is the same moment and slot the main push used
  before.

## Changes

1. **Hooks** (`.pre-commit-config.yaml`).
   - Installed stages are `pre-commit` and `commit-msg`; `pre-push` is removed.
   - Top-level `fail_fast: true`, so a failed lint, type check or unit test never
     spends mutation or stand time. Hook order runs fast to slow.
   - `version-drift` and `mutmut-full` are deleted.
   - The `mutmut` hook runs on `files: ^cveta2/.*\.py$` with `verbose: true`.
   - `integration-tests` moves to the pre-commit stage, runs last, and is filtered
     to `^(cveta2/|tests/integration/|pyproject\.toml$|uv\.lock$)`.
2. **Mutation tool** (`scripts/mutation.py`, rewritten).
   - It reads the staged diff, or `--base REV` (diff against that revision), or
     explicit files, and maps changed lines to top-level functions and methods.
   - It exports the staged tree with `git checkout-index` into a fresh
     temporary workspace.
   - It rewrites that copy's `[tool.mutmut].only_mutate` to the changed files only.
   - It runs the repository venv's `mutmut` there, with `cwd` set to the workspace.
     It never runs `uv run` in the copy, because that would create a new venv.
   - `PYTEST_DEBUG_TEMPROOT` lives inside the workspace.
   - It strips the live-stand variables (`CVAT_INTEGRATION_*`, `MINIO_*`,
     `CLEARML_*`) from the child, so that mutmut never touches a stand.
   - It reports each survivor's diff inline (capped) and deletes the workspace,
     unless `--keep` is given.
   - Exit codes: 0 when the run completes, survivors or not; 0 with a notice when no
     changed function yields mutants; nonzero on a tool, configuration or
     clean-test failure. `--strict` makes survivors fail, for deliberate hardening.
   - Nothing is cached between runs, and concurrent runs from different worktrees
     or agents never share state.
3. **`pyproject.toml`.**
   - Remove `only_mutate`, `cache_invalidation_files`, `on_dependency_change`,
     `[tool.cveta2.mutation.profiles]` and `[tool.cveta2.mutation.equivalent]`.
   - Keep `source_paths`, `pytest_add_cli_args` (`-n 0`) and
     `do_not_mutate_patterns`.
   - Drop `also_copy = ["scripts"]`: the workspace copy carries `scripts/`, and the
     tool test runs outside mutmut.
4. **Integration lifecycle** (`tests/integration/lifecycle.py`).
   - The `.env` arming file and its parser go. A machine is armed when the
     k8s-infra skill is found (`K8S_INFRA_SKILL_DIR`, `~/.agents/skills` or
     `~/.claude/skills`). The gate skips with a notice otherwise.
   - The gate preflights with `infra.py room`. WAIT (exit 3) fails the gate with a
     retry message.
   - The `PRE_COMMIT_REMOTE_BRANCH` push detection goes; "on main" means the checked
     out branch.
   - `tests/integration/.env.example` is deleted.
5. **Remove the generated `mutants/` workspace** (3.8 GB) and its `.gitignore` and
   tool exclusions once nothing writes it. Keep the ignore entries harmlessly if
   other tooling references them.
6. **Constitution and engineering guidance.**
   - Amend the mutation principle: mutation is an advisory, change-scoped check.
   - Amend the hook statements.
   - Bump the constitution version.
   - In `engineering.md`, rewrite setup (no keepalive, no pre-push), mutation,
     integration and the hooks section.
7. **Skills** (the real files in `.claude/skills/`; `.agents/skills/` holds
   symlinks).
   - `commit`: cut to the project-specific rules.
   - `mutation-testing`: cut to running the tool and triaging a survivor, with a
     short "why no mutants" note. `mutation-internals.md` is deleted.
   - `running-integration-tests`: cut to the commands, arming, the tag and cleanup
     rules. `parallel-agents-guide.md` is deleted.
8. **Other documentation.** `AGENTS.md`, `scripts/README.md` (Russian), and the
   comments in `pyproject.toml` and `.pre-commit-config.yaml`. Historical `specs/*`
   and `docs/plans/*` are not rewritten.
9. **Local machine.**
   - Uninstall the now-unused pre-push hook in this clone
     (`uv run pre-commit uninstall -t pre-push`).
   - Update the agent memory notes about pushes and integration.

## Architecture

See [architecture.json](architecture.json). No runtime package module changes.
Tooling stays outside the runtime package
(`tests/test_integration_tool_boundaries.py`), and the lifecycle CLI stays
standard-library only. The rewritten `scripts/mutation.py` keeps those rules: it
uses the standard library, with git and mutmut as subprocesses, and has no
`cveta2` imports. The package's layer contracts (`uv run lint-imports`,
`tests/test_architecture.py`) are unchanged and re-run.

The portable corp-skills `cveta2` skill documents tool usage only. It does not
reference hooks, mutation or the integration lifecycle, so it needs no change.

## Verification

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`,
  `uv run vulture`, `uv run lint-imports`.
- `uv run pytest tests/test_architecture.py tests/test_integration_tool_boundaries.py tests/test_integration_lifecycle.py tests/test_mutation_tool.py tests/test_docs.py`.
- The mutation tool end to end on a real change:
  - a weakened assertion must produce a reported survivor;
  - an untouched tree must report "nothing to mutate";
  - record the per-commit time.
- The full pre-commit suite on the commit, including the live integration gate (not
  skipped).
- A fresh independent review of the whole diff before the push.
- A plain push, with no pre-push hook installed, confirmed with `git ls-remote`.

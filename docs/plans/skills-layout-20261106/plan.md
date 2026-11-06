# Project skills layout: maintenance plan

Date: 2026-11-06. This plan answers the owner's request. Project skills must hold
situational procedures rather than workflow policy. Authored skills must have one
source shared by both hosts through symlinks. The Spec Kit skills must be
regenerated.

## Workflow selection

This is agent-instruction and skill maintenance. The `cveta2` package, its CLI,
its public API and the dataset contract do not change. It therefore takes the
lightweight path of the
[gates simplification](../dev-gates-simplification-20261106/plan.md) precedent:
this plan, [tasks.md](tasks.md), a no-impact [architecture.json](architecture.json)
and dated verification evidence. `.specify/feature.json` is not touched.

## Findings

- `commit` fired on almost every task. Most of it restated engineering guidance
  § "Commits, hooks, and releases", so it was workflow policy, not a skill.
- `mutation-testing` is a situational procedure. It is kept unchanged.
- `running-integration-tests` is a situational procedure. Its "Rules" and
  "Pre-commit gate" sections repeated engineering guidance § "Shared infra" and
  the hook rules.
- engineering guidance contained the step-by-step release procedure. That is
  situational: it applies on `main`, after a merge.
- The layout was inverted. `.claude/skills/<name>` held the sources and
  `.agents/skills/<name>` were symlinks. The shared convention keeps sources in
  `.agents/skills` and uses Claude discovery adapters.

## Changes

1. Fold the unique parts of `commit` into engineering guidance § "Commits, hooks,
   and releases", under three subsections:
   - Commits: message rules.
   - Hooks: rewrite restaging, no edits during the live gate, unrelated
     failures.
   - The commit report.

   Then delete the skill.
2. Add a `release` skill with the semantic-release commands, the failed-hook
   recovery and the report. The standing release policy stays in engineering
   guidance.
3. Slim `running-integration-tests`. Point to engineering guidance § "Shared infra"
   and k8s-infra `run-contract.md` for the stand safety rules. Keep the
   tool-specific rules and a "Gate failures" troubleshooting list.
4. Move the authored skill sources to `.agents/skills/<name>/`. Make
   `.claude/skills/<name>` a relative symlink to `../../.agents/skills/<name>`,
   following the `fat` repository's adapter form. Replace the `.gitignore`
   exceptions with directory patterns, so the real files stay tracked.
5. Keep `speckit-*` as generator-owned per-host copies. They differ only in the
   invocation sigil (`/` or `$`) and in three Claude-only frontmatter keys. Their
   hashes are recorded in `.specify/integrations/*.manifest.json`, so a symlink
   would break one manifest. Regenerate both with
   `specify integration upgrade codex|claude`, using the installed 1.0.13. The CLI
   upgrade to 1.3.1 is left to the owner.
6. Record the layout in engineering guidance § "Project skills". Update the skill
   list and authorization sentence in `AGENTS.md`.
7. Enforce the layout in `tests/test_docs.py`:
   - each authored source is a real directory whose `name` matches;
   - each Claude adapter is the exact relative symlink;
   - there is no Claude-only authored skill;
   - no authored file is gitignored;
   - the `speckit-*` sets match and each file matches its manifest hash.

## Accepted behaviour losses

None. The `commit` content moved into engineering guidance, which every task reads.

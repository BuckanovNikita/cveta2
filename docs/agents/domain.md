# Domain Docs

How the engineering skills consume this repo's domain documentation when exploring the codebase. The repo is single-context.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root.
- **`docs/adr/`**: the ADRs that touch the area you're about to work in.

If either doesn't exist, **proceed silently**. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`, including where it picks one synonym over another.

A concept missing from the glossary is a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_

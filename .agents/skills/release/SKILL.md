---
name: release
description: Use when a cveta2 code release is requested or when assessing the suspended release route.
---

# Code releases are suspended

Read [engineering release policy](../../../docs/agents/engineering.md#releases).
The configured semantic-release branch matcher rejects all release branches before
release processing. Do not restore it, locally merge into main, push main, publish
version tags, or invoke the archived release procedure as part of ordinary delivery.
Find the PR-based release-tooling follow-up in Linear project `cveta2` and report the
suspension. Preserve existing releases and unrelated work.

A separately authorized replacement must be independently reviewed and human-merged
before this skill is updated to enable releases. It must retain semantic-release
ownership, immutable accepted-source checks, shared locking, required acceptance,
separate publication authorization, bounded recovery and the narrow explicit
version/changelog/lockfile release-check exception with message/staging validation.
Publish Git version tags only, never GitHub Releases, release assets or packages.
The existing `release-check` task is checks only and grants no release authorization.

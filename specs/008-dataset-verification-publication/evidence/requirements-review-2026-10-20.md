# Publication requirements review — 2026-10-20

Verdict: the ten custom publication requirements-quality criteria are satisfied.
This review approves the written requirements for implementation; it does not
assert that behavior is implemented, tested, or ready for release.

Scope: the reviewer inspected AGENTS.md, the constitution, engineering guidance,
spec.md, plan.md, research.md, contracts/interfaces.md and checklists/publication.md
for feature 008. The feature selection helper resolved this feature before edits.
Review ownership is limited to the custom checklist and this evidence file.

| Criterion | Assessment and written evidence |
| --- | --- |
| CHK001 | FR-005 defaults to report-only, requires explicit cleanup, separates original validity from requires_cleanup, and excludes structural failures from cleanup. Story 1 and the verify CLI contract reinforce those boundaries. |
| CHK002 | Stories 2–3 require preparation, local review and later upload on the same machine. Corrections require changing inputs/settings and preparing again. FR-011–012 prohibit overwrite and cleanup at upload; plan architecture describes stable snapshots. |
| CHK003 | FR-006 and FR-011 name all four source tables and require copies. FR-013 and the interface payload paragraph name the exact three remote files and exclude reports, images, source evidence and the local preparation record. |
| CHK004 | Story 3 scenario 2 and the clarification require preparation again when a newer parent appears. FR-012 requires latest-parent revalidation; the plan checks it again immediately before publication. |
| CHK005 | FR-007 uses API number as prod_id, preserves aliases/empty policy across renames, rejects ambiguous identities and disappeared parent IDs, and quarantines unknown/empty classes by image. FR-012 also rechecks current classes during upload. |
| CHK006 | FR-008 requires all-root/source coverage before filtering, independent local/S3 roots and symlink containment. Bucket-relative keys must resolve to exactly one approved bucket; per-object probing is explicitly excluded. The research decision rejects inferred mirror relationships. |
| CHK007 | FR-006 and exclusions assign splits externally. FR-003 and FR-009 quantify box geometry, image size, readable supported absolute local images, and nonempty train/val sets with training boxes. |
| CHK008 | FR-014 and the interface contract enumerate the removed fetch keyword, flag, setup command, settings/mappings and unused publisher. They preserve CVAT upload and prohibit automatic user configuration rewriting. Story 4 covers rejection of old callers. |
| CHK009 | FR-002 requires typed prompt-free results and Cveta2Error failures. FR-015 and the CLI contract distinguish verification findings/cancellation, operational/input/config failures and valid results; upload succeeds only after finalization. Story 3 scenario 3 requires a known child identity on partial publication failure without a false success claim. |
| CHK010 | FR-016 and the plan ownership table assign file/media/network/SDK effects to adapters behind typed ports and prompts to interfaces. ClearML remains optional. FR-017 and plan acceptance require tagged live exact-three-file publication, unchanged parent/source evidence, exact-tag cleanup and independent review. |

No unresolved requirement gap was found within these checklist criteria. Runtime
proof, architecture-record validation, task completeness, documentation updates,
package checks, live integration, final independent review and release gates remain
implementation/acceptance obligations; none is marked complete by this review.

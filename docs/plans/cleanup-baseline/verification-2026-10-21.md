# Cleanup verification — 2026-10-21

## Starting state and archive preparation

Local and published main matched
`f6717f0211169f8f94c78da2bfa8dee86bfab602`. The source checkout's only untracked
paths were the explicitly included bugs tree and two unrelated skill links.
An isolated worktree uses branch `refactor/cleanup-baseline`; the source files
remain unchanged while archival prerequisites run.

- `uv sync --frozen --extra clearml`: passed using the existing lockfile and Python 3.12.13.
- `uv run --frozen pytest -n 4 -q --no-header`: 2764 passed in 12.90 seconds; this is the non-live baseline, not integration evidence.
- Shared architecture validator, `--phase plan`: passed after correcting the record's string-valued documentation/contract fields.
- Archive inventory: 110 tracked historical files plus 129 untracked review files, 239 total. Every native-path source equals the isolated checkout; every tar member equals its source bytes.
- Deterministic archive SHA-256: `66dbe1f2eab4385017542e828031e7ff64bb23a5109e4fddec33fa7444ba6211`.
- Existing review SHA256SUMS: 115 matches and 13 mismatches. Both the original manifest and current files are preserved; the new manifest identifies each mismatch without claiming original proof integrity.
- Selected-content scan found no private-key, AWS/GitHub-token, generic literal-credential or inherited-secret matches. One inherited secret value was checked. This bounded pattern scan is not an exhaustive secret audit; existing captured logs use redacted output.

Planning inspection also passed Vulture, the effect checker, all ten import
contracts and 290 documentation/architecture tests in the original checkout.
These pre-change outcomes do not establish final implementation acceptance.

## Remaining acceptance

Checkpoint commit, baseline cutover, code changes, integrated checks, live tests,
fresh independent review, architecture acceptance and release delivery are pending.
Actual outcomes will be appended here; task status lives in [tasks.md](tasks.md).

## Checkpoint and baseline cutover

Checkpoint `af0073e5bd8a8799f0cfd322cfb27c8efd7b747d` passed all configured
pre-commit and commit-message hooks: formatting/lint, imports/effects, mypy,
Vulture, full ordinary tests with coverage, fast mutation, build and lock check.
All 239 committed native-file/archive-member hashes were independently read back
from Git and verified against the committed manifest before retiring any file.

The actual cutover transformation was exercised without writes across the retained
tracked Markdown/Python/TOML inventory. It resolved 13 Markdown references across
10 changed files, including repeated references and the verification deep link;
every original archive source still matched before application. The applied
transformation removes only the 110 inventoried historical tracked records plus
the now-checkpointed archive/manifest. Source-checkout bug files remain intact
until delivery reconciliation. Fixtures stay in tests and were not regenerated.

The 622-line baseline preserves the 30-column schema and current contracts from
features 001 through 008, including both independently named 002 features. It
reconciles later closure of all 134 checked tasks and superseded automatic
publication rather than reviving historical findings. Decision sources use full
implementation SHAs; archive retrieval uses the separate checkpoint SHA.

Constitution 1.5.0 adds recoverable consolidation and baseline deltas without
removing principles or changing templates. Its resolver succeeded; no extension
hooks or unresolved placeholders were present. The temporary sync-impact comment
was reviewed and removed before commit. Governance and Russian contributor
guidance now distinguish module-impact runtime maintenance from documentation-only
no-impact work.

- `uv run --frozen pytest -n 0 -q tests/test_docs.py`: 45 passed, including a new check that the baseline's ordered schema equals the public CSV_COLUMNS contract and expanded nested maintenance-link coverage.
- Next-feature dry run: `001-next-feature`; no new feature directory or active pointer was created.
- `uv build --out-dir <temporary-output>`: wheel and sdist passed. The sdist contains only `specs/baseline.md` under specs and contains no archive container.
- `git diff --check`: passed.

These are cutover checks. Final runtime, mutation/live, independent-review and
release acceptance remain pending.

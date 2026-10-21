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

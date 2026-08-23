#!/usr/bin/env python3
"""Read the mutation profiles out of pyproject.toml and keep ``mutants/`` honest.

Two jobs, both driven by ``scripts/mutation_test.sh``:

``globs --profile <name>``
    Print the mutant-name globs of a profile, one per line. An empty profile
    prints nothing, which the caller turns into a bare ``mutmut run`` -- that
    distinction is load-bearing. mutmut honours a cached verdict only when no
    positional mutant name is given (``if not mutant_names and result is not
    None: continue``), so passing ``"*"`` to mean "everything" would silently
    re-execute every mutant instead of reusing the cache.

``sync-scope``
    Wipe ``mutants/`` when the mutation scope changed. ``Config.config_fingerprint()``
    deliberately hashes only pytest args, timeouts and the type-check command;
    ``only_mutate`` and ``do_not_mutate_patterns`` are excluded because mutmut
    assumes new mutants are born uncached and dropped ones stop being walked.
    That assumption breaks in both directions here: adding a file to
    ``only_mutate`` leaves the mutant tree stale ("0 files mutated, N
    unmodified", observed), and suppressing a call renumbers a function's
    mutants so an old verdict re-attaches to a different mutation. Both are
    silent -- the gate stays green on results that no longer mean anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
MUTANTS_DIR = REPO_ROOT / "mutants"
FINGERPRINT_FILE = MUTANTS_DIR / ".cveta2-scope-fingerprint"

# The mutmut settings that decide *which* mutants exist. A change to any of
# them invalidates the whole tree, not just one function's verdicts.
_SCOPE_KEYS = ("only_mutate", "do_not_mutate", "do_not_mutate_patterns", "source_paths")


def _load_pyproject() -> dict[str, object]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _tool_table(config: dict[str, object], *path: str) -> dict[str, object]:
    node: object = config
    for key in path:
        if not isinstance(node, dict):
            return {}
        node = node.get(key, {})
    return node if isinstance(node, dict) else {}


def profile_globs(name: str) -> list[str]:
    """Return the mutant-name globs of *name*, or exit if it is not defined."""
    profiles = _tool_table(_load_pyproject(), "tool", "cveta2", "mutation", "profiles")
    if name not in profiles:
        known = ", ".join(sorted(profiles)) or "(none defined)"
        sys.exit(f"Unknown mutation profile {name!r}. Known profiles: {known}")
    globs = profiles[name]
    if not isinstance(globs, list) or not all(isinstance(g, str) for g in globs):
        sys.exit(f"Profile {name!r} must be a list of mutant-name glob strings.")
    return [str(g) for g in globs]


def scope_fingerprint() -> str:
    mutmut_config = _tool_table(_load_pyproject(), "tool", "mutmut")
    scope = {key: mutmut_config.get(key) for key in _SCOPE_KEYS}
    payload = json.dumps(scope, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def sync_scope() -> None:
    """Drop a stale mutant tree so the next run regenerates it from scratch."""
    current = scope_fingerprint()
    previous = (
        FINGERPRINT_FILE.read_text(encoding="utf-8").strip()
        if FINGERPRINT_FILE.is_file()
        else None
    )
    if previous == current:
        return
    if MUTANTS_DIR.exists():
        if previous is None:
            print("==> mutants/ has no scope fingerprint; regenerating from scratch.")
        else:
            print(
                f"==> Mutation scope changed ({previous} -> {current}); "
                "wiping mutants/."
            )
        shutil.rmtree(MUTANTS_DIR, ignore_errors=True)
    MUTANTS_DIR.mkdir(parents=True, exist_ok=True)
    FINGERPRINT_FILE.write_text(f"{current}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    globs_parser = sub.add_parser("globs", help="print a profile's mutant-name globs")
    globs_parser.add_argument("--profile", required=True)
    sub.add_parser("sync-scope", help="wipe mutants/ when the mutation scope changed")

    args = parser.parse_args()
    if args.command == "globs":
        for glob in profile_globs(args.profile):
            print(glob)
    else:
        sync_scope()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Reject a commit message that python-semantic-release cannot read.

The version, the tag and CHANGELOG.md are derived from the commit history, so a
subject that misses the conventional form is not a style slip: it silently drops
out of the version calculation, and the release that should have been a `fix`
turns into no release at all.

Merge, revert and autosquash subjects are written by git itself and are exempt -
git runs this hook for `git merge` too.

The `!` marker is checked against the body because the two halves of a breaking
change are computed from different places: `!` alone bumps the version, while the
"BREAKING CHANGES" section of the changelog is built from the footer.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# The types python-semantic-release's conventional parser understands. Only
# `feat`, `fix` and `perf` move the version; the rest exist so that everything
# else is still classified rather than ignored.
TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "style",
    "test",
)

SUBJECT_RE = re.compile(rf"^({'|'.join(TYPES)})(\([^()\s][^()]*\))?(!)?: \S")

# Subjects git generates or that address an earlier commit rather than describing
# a change of its own.
EXEMPT_PREFIXES = ("Merge ", "Revert ", "fixup!", "squash!", "amend!")

BREAKING_FOOTER_RE = re.compile(r"^BREAKING[ -]CHANGE: \S", re.MULTILINE)


def _subject_and_body(message: str) -> tuple[str, str]:
    lines = [line for line in message.splitlines() if not line.startswith("#")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return "", ""
    return lines[0].rstrip(), "\n".join(lines[1:])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: check_commit_msg.py <commit-msg-file>")
        return 1

    subject, body = _subject_and_body(
        Path(args[0]).read_text(encoding="utf-8", errors="replace")
    )
    if not subject or subject.startswith(EXEMPT_PREFIXES):
        return 0

    match = SUBJECT_RE.match(subject)
    if not match:
        print(f"FAILED: not a conventional commit subject:\n    {subject}")
        print(f"Expected `type(scope): description`, type one of: {', '.join(TYPES)}")
        print("For example:  fix(partition): win same-date ties for deletions")
        print("The version, the tag and CHANGELOG.md are computed from these types.")
        return 1

    if match.group(3) and not BREAKING_FOOTER_RE.search(body):
        print(
            "FAILED: `!` marks a breaking change but the body has no footer:\n"
            f"    {subject}"
        )
        print("Add a footer line, otherwise the changelog gets no text for it:")
        print("    BREAKING CHANGE: <what broke and what to do about it>")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
